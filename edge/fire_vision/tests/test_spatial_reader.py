"""Reject syntactically valid artifacts with unsafe paths or broken raw references."""
import json

import h5py
import numpy as np
import pytest

from fire_vision.spatial.reader import Reader, validate_manifest, validate_hdf5
from fire_vision.spatial.storage import RawRecorder, Exporter, sha256
from fire_vision.spatial.sources import SyntheticSource
from fire_vision.spatial.analysis import AnalysisPipeline


def make_result(tmp_path):
    import threading
    directory=tmp_path/'session'
    directory.mkdir()
    source=SyntheticSource({'source':{'frames':2}})
    source.open()
    config={'detector':{'backend':'synthetic'},'pose':{'backend':'synthetic'}}
    pipeline=AnalysisPipeline(config,source.calibration,source.metadata)
    writer=RawRecorder(directory,source.metadata,source.calibration,config)
    for capture in source.captures(threading.Event()):
        ci,di=writer.append(capture)
        writer.analysis(pipeline.process(capture,ci,di))
    writer.close()
    manifest=Exporter(directory,config).finalize(source.metadata,pipeline.features,{})
    return directory,manifest


def update_hash(directory,manifest):
    path=directory/'session.h5'
    manifest['hdf5']['size_bytes']=path.stat().st_size
    manifest['hdf5']['sha256']=sha256(path)
    (directory/'map.json').write_text(json.dumps(manifest))


def test_reader_returns_raw_observation_frames_and_chunked_submap_points(tmp_path):
    directory,manifest=make_result(tmp_path)
    with Reader(directory/'map.json') as reader:
        assert reader.objects()==manifest['objects']
        observation=reader.observation(0)
        rgb,depth=reader.observation_frames(0)
        assert rgb.shape==(48,64,3)
        assert depth.shape==(48,64)
        assert observation['position_m'] is not None
        assert reader.trajectory(0,1).shape==(1,)
        assert reader.points(0,5).shape==(5,3)
        assert reader.points(submap_id=999).shape==(0,3)
        assert reader.raw('imu/accel',0).shape==(3,)
        with pytest.raises((ValueError,IndexError)):
            reader.raw('../meta/json',0)
        with pytest.raises(IndexError):
            reader.observation(-1)


def test_schema_requires_contract_and_rejects_nan_anywhere(tmp_path):
    _,data=make_result(tmp_path)
    validate_manifest(data)
    for key in ('coordinates','features','submaps','objects','quality','time'):
        invalid=dict(data)
        del invalid[key]
        with pytest.raises(ValueError): validate_manifest(invalid)
    data['quality']['metrics']['latency']=float('inf')
    with pytest.raises(ValueError,match='finite|Infinity|NaN'):
        validate_manifest(data)


def test_reader_rejects_escape_absolute_path_and_symlink(tmp_path):
    directory,data=make_result(tmp_path)
    for value in ('../session.h5',str((directory/'session.h5').resolve())):
        data['hdf5']['path']=value
        (directory/'map.json').write_text(json.dumps(data))
        with pytest.raises(ValueError,match='path|relative|escape'):
            Reader(directory/'map.json')
    outside=tmp_path/'elsewhere.h5'
    outside.write_bytes(b'x')
    (directory/'alias.h5').symlink_to(outside)
    data['hdf5']['path']='alias.h5'
    (directory/'map.json').write_text(json.dumps(data))
    with pytest.raises(ValueError,match='path|escape'):
        Reader(directory/'map.json')


@pytest.mark.parametrize('corruption',['raw_length','pose_index','map_pose_index','rigid_matrix','submap','frame_index'])
def test_reader_rejects_corrupt_hdf5_even_when_hash_is_recomputed(tmp_path,corruption):
    directory,data=make_result(tmp_path)
    with h5py.File(directory/'session.h5','r+') as h:
        if corruption=='raw_length':
            h['raw/depth/time_us'].resize(1,axis=0)
        elif corruption=='pose_index':
            rows=h['derived/observations'][:]
            rows['pose_index'][0]=999
            h['derived/observations'][:]=rows
        elif corruption=='map_pose_index':
            h['map/points/pose_index'][0]=999
        elif corruption=='rigid_matrix':
            rows=h['derived/poses'][:]
            rows['T_map_from_depth'][0,0,0]=9
            h['derived/poses'][:]=rows
        elif corruption=='submap':
            rows=h['derived/poses'][:]
            rows['submap_id'][0]=999
            h['derived/poses'][:]=rows
        else:
            h['derived/detections_by_color'][0]=[999,1]
    update_hash(directory,data)
    with pytest.raises(ValueError):
        Reader(directory/'map.json')


def test_manifest_cannot_lie_about_object_position_or_source_reference(tmp_path):
    directory,data=make_result(tmp_path)
    data['objects'][0]['position_m']=[100.,200.,300.]
    with h5py.File(directory/'session.h5') as h:
        with pytest.raises(ValueError,match='position|object'):
            validate_hdf5(h,data)
    data['objects'][0]['observations'][0]['index']=999
    with h5py.File(directory/'session.h5') as h:
        with pytest.raises(ValueError,match='reference|index'):
            validate_hdf5(h,data)


def test_reader_rejects_unfinalized_file_and_nan_json_before_opening(tmp_path):
    directory,data=make_result(tmp_path)
    with h5py.File(directory/'session.h5','r+') as h:
        h.attrs['finalized']=False
    update_hash(directory,data)
    with pytest.raises(ValueError,match='final'):
        Reader(directory/'map.json')


def test_hdf5_external_link_cannot_escape_result_storage(tmp_path):
    directory,data=make_result(tmp_path)
    outside=tmp_path/'outside.h5'
    with h5py.File(outside,'w') as h:
        h.create_dataset('secret',data=[4])
    with h5py.File(directory/'session.h5','r+') as h:
        h['external_raw']=h5py.ExternalLink(str(outside),'/secret')
    update_hash(directory,data)
    with pytest.raises(ValueError,match='external|link'):
        Reader(directory/'map.json')


def test_point_arrays_and_raw_scale_are_validated_before_use(tmp_path):
    directory,data=make_result(tmp_path)
    with h5py.File(directory/'session.h5','r+') as h:
        h['raw/depth/depth_scale_m'][0]=0
    update_hash(directory,data)
    with pytest.raises(ValueError,match='scale'):
        Reader(directory/'map.json')


def test_synthetic_origin_and_fixture_pose_flags_cannot_be_changed_independently(tmp_path):
    directory,data=make_result(tmp_path)
    with h5py.File(directory/'session.h5','r+') as h:
        metadata=json.loads(h['meta/json'][()].decode())
        metadata['synthetic']=False
        h['meta/json'][()]=json.dumps(metadata)
    update_hash(directory,data)
    with pytest.raises(ValueError,match='synthetic'):
        Reader(directory/'map.json')


def test_hdf5_position_status_cannot_claim_map_valid_with_null_position(tmp_path):
    directory,data=make_result(tmp_path)
    with h5py.File(directory/'session.h5','r+') as h:
        rows=h['derived/observations'][:]
        rows['point_camera_m'][0]=np.nan
        rows['position_m'][0]=np.nan
        rows['failure_reason'][0]=b'invalid_depth'
        h['derived/observations'][:]=rows
        with pytest.raises(ValueError,match='status|position'):
            validate_hdf5(h,data)
