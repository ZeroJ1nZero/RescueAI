"""Read finalized result contracts with schema, hash and record-reference checks.

Validation reads bounded HDF5 blocks; it never loads raw video sessions into RAM.
"""
from __future__ import annotations

from importlib.resources import files
import json
import math
from pathlib import Path

import h5py
import numpy as np
from jsonschema import Draft202012Validator

from ..object_projection import rigid_matrix
from .geometry import AXIS_MAP_FROM_OPTICAL
from .storage import PAIR, DETECTION, POSE, OBSERVATION, decode, sha256


def _finite_json(value):
    if isinstance(value,float) and not math.isfinite(value):
        raise ValueError('JSON numbers must be finite; NaN and Infinity are forbidden')
    if isinstance(value,dict):
        for item in value.values(): _finite_json(item)
    elif isinstance(value,list):
        for item in value: _finite_json(item)


def validate_manifest(data):
    _finite_json(data)
    schema=json.loads(files(__package__).joinpath('map.schema.json').read_text())
    error=next(Draft202012Validator(schema).iter_errors(data),None)
    if error is not None:
        raise ValueError(f'map schema violation at {list(error.absolute_path)}: {error.message}')
    if not np.allclose(data['coordinates']['T_initial_map_from_depth'],AXIS_MAP_FROM_OPTICAL):
        raise ValueError('initial axis transform does not match coordinate contract')
    if data['synthetic'] and data['status']=='complete':
        raise ValueError('synthetic data cannot be declared complete measured mapping')
    ids=[s['id'] for s in data['submaps']]
    if len(set(ids))!=len(ids):
        raise ValueError('duplicate submap id')
    for submap in data['submaps']:
        if submap['alignment_status']=='local_only' and submap['aligned_to'] is not None:
            raise ValueError('local-only submap cannot claim external alignment')
        if submap['aligned_to'] is not None and submap['aligned_to'] not in ids:
            raise ValueError('submap alignment reference does not exist')
    return data


def _dataset(h5,path,dtype=None,tail=None):
    if path not in h5 or not isinstance(h5[path],h5py.Dataset):
        raise ValueError(f'missing dataset reference: {path}')
    ds=h5[path]
    if dtype is not None and ds.dtype != dtype:
        raise ValueError(f'dataset dtype mismatch: {path}')
    if tail is not None and (ds.ndim != 1+len(tail) or ds.shape[1:] != tail):
        raise ValueError(f'dataset shape mismatch: {path}')
    return ds


def _blocks(dataset,size=4096):
    for start in range(0,len(dataset),size):
        yield dataset[start:start+size]


def _self_contained(h5):
    pending=[h5['/']]
    visited=set()
    while pending:
        group=pending.pop()
        address=h5py.h5o.get_info(group.id).addr
        if address in visited: continue
        visited.add(address)
        for name in group:
            link=group.get(name,getlink=True)
            if not isinstance(link,h5py.HardLink):
                raise ValueError('external or symbolic HDF5 links are not permitted')
            item=group[name]
            if isinstance(item,h5py.Group):
                pending.append(item)
            elif item.is_virtual or item.external:
                raise ValueError('external or virtual HDF5 dataset storage is not permitted')


def _indices(indices,count,name,missing=False):
    values=np.asarray(indices)
    if np.any(values < (-1 if missing else 0)) or np.any(values>=count):
        raise ValueError(f'invalid {name} reference index')


def _vector(value,name,nullable=False):
    value=np.asarray(value)
    if nullable and np.isnan(value).all(): return None
    if not np.isfinite(value).all():
        raise ValueError(f'invalid {name} position/vector')
    return value


def _row_dict(row):
    result={}
    for key in row.dtype.names:
        value=row[key]
        if isinstance(value,np.ndarray):
            result[key]=None if np.isnan(value).all() else value.tolist()
        elif isinstance(value,(bytes,np.bytes_)):
            result[key]=decode(value)
        elif isinstance(value,np.generic):
            value=value.item()
            result[key]=None if isinstance(value,float) and not math.isfinite(value) else value
        else:
            result[key]=value
    return result


def validate_hdf5(h5,result):
    """Validate reference integrity before publishing; finalized is Reader's gate."""
    validate_manifest(result)
    _self_contained(h5)
    if decode(h5.attrs.get('schema_version','')) != result['schema_version']:
        raise ValueError('HDF5 schema version differs from manifest')
    if bool(h5.attrs.get('synthetic',False)) != result['synthetic']:
        raise ValueError('HDF5 synthetic origin differs from manifest')
    for path in ('/meta/json','/meta/config','/calibration/json'):
        value=_dataset(h5,path)
        if value.shape != ():
            raise ValueError(f'metadata must be scalar JSON: {path}')
        parsed=json.loads(decode(value[()]))
        _finite_json(parsed)
        if path=='/meta/json' and bool(parsed.get('synthetic',False))!=result['synthetic']:
            raise ValueError('metadata synthetic origin differs from manifest')
    counts={}
    for stream in ('color','depth','imu/accel','imu/gyro'):
        prefix='/raw/'+stream
        times=_dataset(h5,prefix+'/time_us',np.dtype('<i8'),())
        count=len(times)
        counts[stream]=count
        for field in ('frame_id','sensor_timestamp','host_monotonic_ns'):
            if len(_dataset(h5,prefix+'/'+field,np.dtype('<i8'),())) != count:
                raise ValueError(f'raw stream length mismatch: {prefix}/{field}')
        g=h5[prefix]
        if 'data' not in g:
            if count: raise ValueError(f'raw dataset absent with nonempty times: {prefix}')
        else:
            data=_dataset(h5,prefix+'/data')
            if len(data)!=count:
                raise ValueError(f'raw stream length mismatch: {prefix}/data')
            if stream=='color' and (data.ndim!=4 or data.shape[-1]!=3 or data.dtype!=np.uint8):
                raise ValueError('color must be uint8 NxHxWx3 RGB')
            if stream=='depth' and (data.ndim!=3 or data.dtype.kind not in 'uif' or data.dtype.itemsize<2):
                raise ValueError('depth must be a numeric raw NxHxW array')
            if stream.startswith('imu/') and (data.ndim!=2 or data.shape[1:]!=(3,) or data.dtype.kind!='f'):
                raise ValueError('IMU must be a floating Nx3 array')
        if count and (not g.attrs.get('timestamp_unit') or not g.attrs.get('clock')):
            raise ValueError(f'raw stream clock/unit absent: {prefix}')
        if stream=='depth':
            scale=_dataset(h5,prefix+'/depth_scale_m',np.dtype('<f8'),())
            if len(scale)!=count:
                raise ValueError('depth scale length differs from frame count')
            for values in _blocks(scale):
                if not np.isfinite(values).all() or np.any(values<=0):
                    raise ValueError('invalid raw depth scale')
    if counts['color'] and (h5['/raw/color'].attrs.get('channel_order')!='RGB' or h5['/raw/color'].attrs.get('color_space')!='sRGB'):
        raise ValueError('color channel order/representation absent')
    poses=_dataset(h5,'/derived/poses',POSE,())
    fixture_poses=_dataset(h5,'/raw/synthetic_poses',np.dtype('<f8'),(4,4))
    if len(fixture_poses)!=counts['depth']:
        raise ValueError('synthetic pose fixture length differs from raw depth count')
    for chunk in _blocks(fixture_poses):
        for matrix in chunk:
            if np.isnan(matrix).all(): continue
            if not result['synthetic']:
                raise ValueError('synthetic fixture pose cannot be attached to real input')
            rigid_matrix(matrix)
    detections=_dataset(h5,'/derived/detections',DETECTION,())
    observations=_dataset(h5,'/derived/observations',OBSERVATION,())
    pairs=_dataset(h5,'/sync/pairs',PAIR,())
    submaps={s['id']:s for s in result['submaps']}
    config=json.loads(decode(h5['/meta/config'][()]))
    tolerance=int(config.get('sync',{}).get('tolerance_us',20_000))
    for rows in _blocks(pairs):
        _indices(rows['color_index'],counts['color'],'RGB pair',True)
        _indices(rows['depth_index'],counts['depth'],'depth pair',True)
        for row in rows:
            ci,di=int(row['color_index']),int(row['depth_index'])
            if ci>=0 and di>=0:
                delta=int(h5['/raw/depth/time_us'][di])-int(h5['/raw/color/time_us'][ci])
                if int(row['delta_us'])!=delta:
                    raise ValueError('RGB-depth pair delta differs from raw times')
            if row['valid'] and (ci<0 or di<0 or abs(int(row['delta_us']))>tolerance or decode(row['reason'])!='ok'):
                raise ValueError('valid RGB-depth pair exceeds time tolerance or has missing data')
            if row['valid'] and h5['/raw/color'].attrs['clock'] != h5['/raw/depth'].attrs['clock']:
                raise ValueError('valid RGB-depth pair uses unconverted unrelated clocks')
    tracked_submaps=set()
    for rows in _blocks(poses):
        _indices(rows['depth_index'],counts['depth'],'pose depth',True)
        for row in rows:
            di=int(row['depth_index'])
            if di>=0 and int(row['time_us']) != int(h5['/raw/depth/time_us'][di]):
                raise ValueError('pose timestamp differs from source depth timestamp')
            if decode(row['status'])=='tracked':
                if di<0 or int(row['submap_id']) not in submaps:
                    raise ValueError('tracked pose requires valid depth/submap reference')
                rigid_matrix(row['T_map_from_depth'])
                tracked_submaps.add(int(row['submap_id']))
                if row['synthetic'] and not result['synthetic']:
                    raise ValueError('synthetic pose cannot be marked as real sensor result')
            elif not np.isnan(row['T_map_from_depth']).all():
                raise ValueError('invalid pose must not carry a map transform')
    if tracked_submaps!=set(submaps):
        raise ValueError('manifest submaps differ from tracked pose records')
    for sid,submap in submaps.items():
        index=submap['origin_pose_index']
        _indices([index],len(poses),'submap origin')
        row=poses[index]
        if int(row['submap_id'])!=sid or decode(row['status'])!='tracked':
            raise ValueError('submap origin does not reference its valid pose')
    for rows in _blocks(detections):
        _indices(rows['color_index'],counts['color'],'detection color')
        if not np.isfinite(rows['confidence']).all() or np.any((rows['confidence']<0)|(rows['confidence']>1)):
            raise ValueError('invalid detection confidence')
        boxes=rows['bbox']
        if not np.isfinite(boxes).all() or np.any(boxes[:,:2]<0) or np.any(boxes[:,2:]<=boxes[:,:2]):
            raise ValueError('invalid detection bbox')
        if not result['synthetic'] and rows['synthetic'].any():
            raise ValueError('synthetic detections cannot be marked real')
    for rows in _blocks(observations):
        _indices(rows['color_index'],counts['color'],'observation color')
        _indices(rows['depth_index'],counts['depth'],'observation depth',True)
        _indices(rows['detection_index'],len(detections),'observation detection')
        _indices(rows['pose_index'],len(poses),'observation pose')
        for row in rows:
            det=detections[int(row['detection_index'])]
            pose=poses[int(row['pose_index'])]
            if int(row['color_index'])!=int(det['color_index']) or decode(row['class'])!=decode(det['class']):
                raise ValueError('observation detection reference does not match source')
            if not np.allclose(row['bbox'],det['bbox']) or not np.isclose(row['detection_confidence'],det['confidence']):
                raise ValueError('observation detection bbox/confidence mismatch')
            if int(row['depth_index'])!=int(pose['depth_index']):
                raise ValueError('observation pose depth reference mismatch')
            if int(row['time_us'])!=int(h5['/raw/color/time_us'][int(row['color_index'])]):
                raise ValueError('observation time differs from raw RGB time')
            camera=_vector(row['point_camera_m'],'camera',True)
            position=_vector(row['position_m'],'map',True)
            ratio=float(row['valid_depth_ratio'])
            variance=float(row['depth_variance_m2'])
            if not math.isfinite(ratio) or not 0<=ratio<=1 or (not math.isnan(variance) and (not math.isfinite(variance) or variance<0)):
                raise ValueError('invalid observation depth quality')
            if position is not None:
                if camera is None or decode(pose['status'])!='tracked' or int(row['submap_id'])!=int(pose['submap_id']):
                    raise ValueError('map position requires valid camera point/pose/submap')
                expected=pose['T_map_from_depth'][:3,:3]@camera+pose['T_map_from_depth'][:3,3]
                if not np.allclose(position,expected,atol=1e-6):
                    raise ValueError('map position disagrees with final pose')
                if decode(row['position_status'])!='map_valid' or decode(row['failure_reason']):
                    raise ValueError('map position status/failure does not match valid map position')
            elif not decode(row['failure_reason']):
                raise ValueError('null map position requires failure reason')
            elif decode(row['position_status'])!=('camera_valid' if camera is not None else 'invalid'):
                raise ValueError('position status disagrees with available camera/map position')
            if not result['synthetic'] and row['synthetic']:
                raise ValueError('synthetic observation cannot be marked real')
    for name,target in [('detections_by_color',detections),('observations_by_color',observations)]:
        ds=_dataset(h5,'/derived/'+name,np.dtype('<i8'),(2,))
        if len(ds)!=counts['color']:
            raise ValueError('frame index length differs from RGB frame count')
        total=0
        for ci in range(len(ds)):
            start,count=map(int,ds[ci])
            if count<0 or start<(-1 if count==0 else 0) or (count and start+count>len(target)):
                raise ValueError('invalid per-frame derived record index')
            if count:
                if not np.all(target[start:start+count]['color_index']==ci):
                    raise ValueError('per-frame derived index references another RGB frame')
                total+=count
        if total!=len(target):
            raise ValueError('per-frame derived indices do not cover all records')
    for group in ('/derived/surface_points','/map/points'):
        points=_dataset(h5,group+'/positions',np.dtype('<f4'),(3,))
        colors=_dataset(h5,group+'/colors',np.dtype('u1'),(3,))
        pids=_dataset(h5,group+'/pose_index',np.dtype('<i8'),())
        dids=_dataset(h5,group+'/depth_index',np.dtype('<i8'),())
        sids=_dataset(h5,group+'/submap_id',np.dtype('<i8'),()) if group=='/map/points' else None
        if sids is not None and len(sids)!=len(points):
            raise ValueError('point submap dataset length differs')
        if any(len(ds)!=len(points) for ds in (colors,pids,dids)):
            raise ValueError('point dataset lengths differ')
        for start in range(0,len(points),4096):
            end=start+4096
            if not np.isfinite(points[start:end]).all():
                raise ValueError('point dataset contains invalid numeric values')
            ids=pids[start:end]
            _indices(ids,len(poses),'point pose')
            _indices(dids[start:end],counts['depth'],'point depth')
            for pi in np.unique(ids):
                pose=poses[int(pi)]
                if not np.all(dids[start:end][ids==pi]==pose['depth_index']):
                    raise ValueError('point depth reference differs from referenced pose')
                if group=='/map/points' and decode(pose['status'])!='tracked':
                    raise ValueError('map point references an invalid pose')
                if sids is not None and not np.all(sids[start:end][ids==pi]==pose['submap_id']):
                    raise ValueError('point submap differs from referenced pose')
    for name,path in result['datasets'].items():
        _dataset(h5,path)
    expected={'points':'/map/points/positions','point_colors':'/map/points/colors','point_pose_index':'/map/points/pose_index',
              'point_submap_id':'/map/points/submap_id','trajectory':'/derived/poses','observations':'/derived/observations'}
    if result['datasets']!=expected:
        raise ValueError('manifest dataset reference semantic mismatch')
    events=_dataset(h5,result['quality']['events_dataset'])
    for chunk in _blocks(events):
        for value in chunk:
            _finite_json(json.loads(decode(value)))
    _validate_objects(h5,result)
    return True


def _validate_objects(h5,result):
    observations=h5['/derived/observations']
    seen=set()
    object_ids=set()
    for obj in result['objects']:
        if obj['id'] in object_ids:
            raise ValueError('duplicate manifest object id')
        object_ids.add(obj['id'])
        refs=obj['observations']
        indices=[ref['index'] for ref in refs]
        _indices(indices,len(observations),'object observation')
        if len(set(indices))!=len(indices) or any(index in seen for index in indices):
            raise ValueError('duplicate object observation reference')
        seen.update(indices)
        if obj['observation_count']!=len(indices):
            raise ValueError('object observation count mismatch')
        times=[]
        latest=None
        for index in indices:
            row=observations[index]
            if decode(row['object_id'])!=obj['id'] or decode(row['class'])!=obj['class']:
                raise ValueError('object observation identity/class mismatch')
            times.append(int(row['time_us']))
            if latest is None or int(row['time_us'])>=int(latest['time_us']):
                latest=row
        if obj['first_seen_us']!=min(times) or obj['last_seen_us']!=max(times):
            raise ValueError('object observation time interval mismatch')
        position=_vector(latest['position_m'],'object',True)
        if (obj['position_m'] is None)!=(position is None) or (position is not None and not np.allclose(obj['position_m'],position)):
            raise ValueError('object position differs from referenced observation')
        sid=int(latest['submap_id'])
        if obj['submap_id']!=(sid if sid>=0 else None):
            raise ValueError('object submap reference mismatch')
        if not math.isclose(obj['detection_confidence'],float(latest['detection_confidence']),abs_tol=1e-7):
            raise ValueError('object detection confidence mismatch')
        for key in ('position_status','motion_status'):
            if obj[key]!=decode(latest[key]):
                raise ValueError(f'object {key} mismatch')
        if obj['failure_reason']!=(decode(latest['failure_reason']) or None) or obj['synthetic']!=bool(latest['synthetic']):
            raise ValueError('object failure/synthetic status mismatch')
    if len(seen)!=len(observations):
        raise ValueError('manifest object references do not cover all observations')


class Reader:
    def __init__(self,map_path,verify_hash=True):
        self.path=Path(map_path).resolve()
        self.manifest=json.loads(self.path.read_text(encoding='utf-8'),parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f'nonfinite JSON {value}')))
        validate_manifest(self.manifest)
        reference=Path(self.manifest['hdf5']['path'])
        if reference.is_absolute() or '..' in reference.parts or '\\' in str(reference):
            raise ValueError('HDF5 path must be relative and cannot escape result directory')
        target=(self.path.parent/reference).resolve()
        if not target.is_relative_to(self.path.parent) or target==self.path.parent:
            raise ValueError('HDF5 path escapes result directory')
        if not target.is_file():
            raise ValueError('HDF5 reference path is not a file')
        if target.stat().st_size!=self.manifest['hdf5']['size_bytes']:
            raise ValueError('HDF5 size differs from manifest')
        if verify_hash and sha256(target)!=self.manifest['hdf5']['sha256']:
            raise ValueError('HDF5 hash differs from manifest')
        self.h5=h5py.File(target,'r')
        try:
            if not bool(self.h5.attrs.get('finalized',False)):
                raise ValueError('HDF5 is not finalized')
            validate_hdf5(self.h5,self.manifest)
        except BaseException:
            self.h5.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self,*args):
        self.close()

    def close(self):
        self.h5.close()

    def raw(self,stream,index):
        if stream not in ('color','depth','imu/accel','imu/gyro'):
            raise ValueError('unsupported raw stream')
        ds=self.h5['/raw/'+stream+'/data']
        _check_index(index,len(ds))
        return ds[index]

    def objects(self):
        return self.manifest['objects']

    def observation(self,index):
        ds=self.h5['/derived/observations']
        _check_index(index,len(ds))
        return _row_dict(ds[index])

    def observation_frames(self,index):
        row=self.observation(index)
        return (self.raw('color',row['color_index']),
                self.raw('depth',row['depth_index']) if row['depth_index']>=0 else None)

    def trajectory(self,start=0,stop=None):
        return self.h5['/derived/poses'][start:stop]

    def points(self,start=0,stop=None,submap_id=None):
        ds=self.h5['/map/points/positions']
        if submap_id is None and len(self.manifest['submaps'])>1:
            raise ValueError('independent submaps require an explicit submap_id')
        if submap_id is None:
            return ds[start:stop]
        start,stop,_=slice(start,stop).indices(len(ds))
        chunks=[]
        for offset in range(start,stop,4096):
            end=min(stop,offset+4096)
            ids=self.h5['/map/points/pose_index'][offset:end]
            mask=np.zeros(len(ids),bool)
            for pi in np.unique(ids):
                if int(self.h5['/derived/poses'][int(pi)]['submap_id'])==submap_id:
                    mask|=ids==pi
            if mask.any(): chunks.append(ds[offset:end][mask])
        return np.concatenate(chunks) if chunks else np.empty((0,3),np.float32)


def _check_index(index,count):
    if not isinstance(index,(int,np.integer)) or isinstance(index,bool) or not 0<=index<count:
        raise IndexError('record index out of range')
