"""Owned raw sensor inputs; no inference or HDF5 writes occur here.

Orbbec APIs are audited against pyorbbecsdk v2-main commit
68cdfa181e09f0ddd0f21b77dff29cb3e7a0f0d2. Runtime SDK/device capability
checks remain mandatory; no camera was attached during development.
"""
from __future__ import annotations

import importlib
import importlib.metadata
import json
from pathlib import Path
import queue
import time

import numpy as np

from .types import Capture, Sample


def _settings(config):
    source = config.get('source', {})
    return {'kind': source} if isinstance(source, str) else source


def _read_json(dataset):
    value = dataset[()]
    return json.loads(value.decode() if isinstance(value, bytes) else value)


class SyntheticSource:
    """Small deterministic fixture. Every output is explicitly synthetic."""
    def __init__(self, config):
        self.config = _settings(config)

    def open(self):
        c = self.config
        self.width, self.height = int(c.get('width', 64)), int(c.get('height', 48))
        self.fps, self.frames = float(c.get('fps', 15)), int(c.get('frames', 30))
        self.scale = float(c.get('depth_scale_m', .001))
        self.imu_hz = float(c.get('imu_hz', 100))
        if min(self.width, self.height, self.fps, self.scale, self.imu_hz) <= 0 or self.frames < 1:
            raise ValueError('positive synthetic dimensions, rates, scale and frames required')
        if not np.isfinite([self.fps,self.scale,self.imu_hz]).all() or 2/self.scale > 65535:
            raise ValueError('synthetic scale must represent 2 meters as uint16')
        intr = dict(K=[[60.,0.,self.width/2],[0.,60.,self.height/2],[0.,0.,1.]],
                    distortion=[0.,0.,0.,0.,0.],width=self.width,height=self.height,
                    distortion_model='none')
        self.calibration = dict(color=intr.copy(),depth=intr.copy(),
                                T_color_from_depth=np.eye(4).tolist(),
                                depth_registered_to_color=True,version='synthetic-fixture-v1')
        self.metadata = dict(synthetic=True, device='synthetic RGB-D/IMU fixture',
                             sdk=None,firmware=None,settings=dict(c),
                             imu={'enabled':True,'accel_unit':'m/s^2','gyro_unit':'rad/s',
                                  'axes':'fixture depth optical','includes_gravity':True},
                             clock_conversion={'method':'shared synthetic device epoch subtraction',
                                               'sensor_origin_us':1_000_000,'synchronization':'synthetic_known'})

    def captures(self, stop_event):
        start = time.monotonic_ns()
        next_imu = 0
        step_imu = 1_000_000/self.imu_hz
        for i in range(self.frames):
            if stop_event.is_set():
                return
            t = round(i*1_000_000/self.fps)
            if self.config.get('realtime', False):
                if stop_event.wait(max(0,(start+t*1000-time.monotonic_ns())/1e9)):
                    return
            yy,xx = np.indices((self.height,self.width))
            color = np.stack(((xx*7+i*3)%256,(yy*9)%256,((xx+yy)*5)%256),axis=-1).astype(np.uint8)
            # A red rectangle is fixture evidence, never a learned object label.
            color[self.height//3:2*self.height//3,self.width//3:2*self.width//3] = [255,0,0]
            depth = np.full((self.height,self.width),round(2/self.scale),np.uint16)
            depth[0,:] = 0
            imu = []
            end = (i+1)*1_000_000/self.fps
            while next_imu*step_imu < end:
                it = round(next_imu*step_imu)
                for stream,data in [('accel',[0.,9.80665,0.]),('gyro',[0.,0.,.01])]:
                    imu.append(Sample(stream,np.array(data,np.float64),next_imu,1_000_000+it,
                                      'us','synthetic_device',start+it*1000,it))
                next_imu += 1
            pose = np.eye(4)
            pose[0,3] = i*.01
            yield Capture(Sample('color',color,i,1_000_000+t+1000,'us','synthetic_device',start+(t+1000)*1000,t+1000),
                          Sample('depth',depth,i,1_000_000+t,'us','synthetic_device',start+t*1000,t,self.scale),
                          imu,pose)

    def close(self):
        pass


class ReplaySource:
    """Merge raw stream cursors with bounded memory; each array is read once."""
    def __init__(self, path, config):
        self.path = Path(path).resolve()
        self.config = _settings(config)
        self.file = None

    def open(self):
        import h5py
        self.file = h5py.File(self.path,'r')
        try:
            self.metadata = _read_json(self.file['/meta/json'])
            self.calibration = _read_json(self.file['/calibration/json'])
            self.metadata['replay'] = {'source_path':str(self.path),'raw_values_preserved':True}
            self.metadata.setdefault('synthetic',False)
        except BaseException:
            self.close()
            raise

    def _sample(self, stream, group, index):
        g = self.file[group]
        return Sample(stream,np.array(g['data'][index],copy=True),int(g['frame_id'][index]),
                      int(g['sensor_timestamp'][index]),str(g.attrs['timestamp_unit']),
                      str(g.attrs['clock']),int(g['host_monotonic_ns'][index]),
                      int(g['time_us'][index]),float(g['depth_scale_m'][index]) if stream=='depth' else None)

    def captures(self, stop_event):
        # Order by preserved host receive time, not resettable device clock.
        cursors = {}
        for stream in ('color','depth','accel','gyro'):
            path = '/raw/'+('imu/' if stream in ('accel','gyro') else '')+stream
            if path in self.file and 'data' in self.file[path]:
                cursors[stream] = [path,0,len(self.file[path]['data'])]
        wall_start = time.monotonic()
        host_start = None
        while not stop_event.is_set():
            choices = [(int(self.file[p]['host_monotonic_ns'][i]),stream) for stream,(p,i,n) in cursors.items() if i<n]
            if not choices:
                return
            host,stream = min(choices)
            if host_start is None:
                host_start = host
            if self.config.get('realtime',False):
                delay = (host-host_start)/1e9-(time.monotonic()-wall_start)
                if stop_event.wait(max(0,delay)):
                    return
            path,index,_ = cursors[stream]
            sample = self._sample(stream,path,index)
            cursors[stream][1] += 1
            capture = Capture()
            if stream in ('accel','gyro'):
                capture.imu.append(sample)
            else:
                setattr(capture,stream,sample)
                if stream=='depth' and self.metadata['synthetic'] and '/raw/synthetic_poses' in self.file:
                    poses = self.file['/raw/synthetic_poses']
                    if index < len(poses):
                        pose = np.array(poses[index],copy=True)
                        if np.isfinite(pose).all():
                            capture.synthetic_pose = pose
            yield capture

    def close(self):
        if self.file is not None:
            self.file.close()
            self.file = None


class OrbbecSource:
    """Native RGB/Y16 recording, independent high-rate IMU callbacks.

    SDK alignment is intentionally disabled so raw depth remains untouched.
    Frame.get_data() currently copies in the audited wrapper; an additional
    np.copy makes ownership explicit across older wrapper implementations.
    """
    def __init__(self, config):
        self.config = _settings(config)
        self.pipeline = None
        self.imu_sensors = []
        self._fatal = None
        self._origin_us = None
        capacity=int(self.config.get('imu_queue_size',2048))
        if capacity < 1:
            raise ValueError('IMU raw queue size must be positive')
        self._queue = queue.Queue(maxsize=capacity)
        self._last_ids = {}

    def open(self):
        try:
            self.sdk = importlib.import_module('pyorbbecsdk')
        except ImportError as e:
            raise RuntimeError('Orbbec source requires the official pyorbbecsdk module (pyorbbecsdk2 distribution)') from e
        sdk,c = self.sdk,self.config
        try:
            self.context = sdk.Context()
            devices = self.context.query_devices()
            if devices.get_count() < 1:
                raise RuntimeError('Orbbec camera not connected')
            if c.get('serial'):
                self.device = devices.get_device_by_serial_number(c['serial'])
            elif devices.get_count()!=1:
                raise RuntimeError('multiple Orbbec devices: configure source.serial')
            else:
                self.device = devices.get_device_by_index(0)
            info = self.device.get_device_info()
            model = info.get_name()
            if c.get('expected_model','Orbbec Gemini 2') != model:
                raise RuntimeError(f'unexpected camera model {model!r}; configure exact expected_model after inspection')
            self.pipeline = sdk.Pipeline(self.device)
            sdk_config = sdk.Config()
            profiles = {}
            for stream,sensor,fmt in [('color',sdk.OBSensorType.COLOR_SENSOR,sdk.OBFormat.RGB),
                                      ('depth',sdk.OBSensorType.DEPTH_SENSOR,sdk.OBFormat.Y16)]:
                p = self.pipeline.get_stream_profile_list(sensor).get_video_stream_profile(
                    int(c.get(stream+'_width',640)),int(c.get(stream+'_height',480)),fmt,int(c.get('fps',30)))
                sdk_config.enable_stream(p)
                profiles[stream] = p
            # ANY_SITUATION retains unmatched frames; spatial synchronization is downstream.
            sdk_config.set_frame_aggregate_output_mode(sdk.OBFrameAggregateOutputMode.ANY_SITUATION)
            self.pipeline.start(sdk_config)
            self._running = True
            deadline = time.monotonic()+float(c.get('timeout_seconds',5))
            first = None
            while time.monotonic()<deadline:
                frame_set = self.pipeline.wait_for_frames(100)
                if frame_set is not None and (frame_set.get_color_frame() or frame_set.get_depth_frame()):
                    first = frame_set
                    break
            if first is None:
                raise RuntimeError('Orbbec camera timed out during startup')
            anchor_frames=[f for f in (first.get_color_frame(),first.get_depth_frame()) if f is not None]
            self._origin_us=min(int(f.get_timestamp_us()) for f in anchor_frames)
            self._host_origin=time.monotonic_ns()
            params=self.pipeline.get_camera_param()
            self.calibration = {
                'color':self._intrinsic(params.rgb_intrinsic,params.rgb_distortion),
                'depth':self._native_depth_intrinsic(model,params.depth_intrinsic,params.depth_distortion),
                'T_color_from_depth':self._extrinsic(params.transform),
                'depth_registered_to_color':False,'version':'sdk-runtime-native-profiles'}
            versions={}
            for package in ('pyorbbecsdk2','pyorbbecsdk'):
                try:
                    versions[package]=importlib.metadata.version(package)
                except importlib.metadata.PackageNotFoundError:
                    pass
            self.metadata = dict(synthetic=False,device={'model':model,'serial':info.get_serial_number(),
                'connection':info.get_connection_type(),'pid':int(info.get_pid()),'vid':int(info.get_vid())},
                sdk={'version':str(sdk.get_version()),'distributions':versions,
                     'api_audit_commit':'68cdfa181e09f0ddd0f21b77dff29cb3e7a0f0d2'},
                firmware=info.get_firmware_version(),settings={'streams':{
                    k:{'width':p.get_width(),'height':p.get_height(),'fps':p.get_fps(),'format':str(p.get_format())}
                    for k,p in profiles.items()},'properties':self._properties()},
                clock_conversion={'method':'shared device microsecond origin subtraction; no drift correction',
                    'sensor_origin_us':self._origin_us,'host_anchor_monotonic_ns':self._host_origin,
                    'synchronization':'device clock shared; hardware RGB-depth sync not verified'},
                imu={'enabled':False,'accel_unit':'m/s^2','gyro_unit':'rad/s',
                    'axes':'native SDK sensor axes; camera alignment not verified','includes_gravity':None})
            if c.get('imu',True):
                self._start_imu(profiles['depth'])
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _intrinsic(intr,dist):
        model=getattr(dist,'model',None)
        model_name=getattr(model,'name',str(model)).lower()
        if '.' in model_name:
            model_name=model_name.rsplit('.',1)[-1]
        coefficients=[float(getattr(dist,n,0.)) for n in ('k1','k2','p1','p2','k3','k4','k5','k6')]
        return {'K':[[float(intr.fx),0.,float(intr.cx)],[0.,float(intr.fy),float(intr.cy)],[0.,0.,1.]],
                'width':int(intr.width),'height':int(intr.height),'distortion':coefficients,
                'distortion_model':model_name,'sdk_distortion_model':str(model)}

    @staticmethod
    def _native_depth_intrinsic(model,intr,dist):
        calibration=OrbbecSource._intrinsic(intr,dist)
        # Orbbec's native-image distortion table explicitly lists Gemini 2
        # original depth as rectified and original color as distorted. Preserve
        # factory lens coefficients, but never undistort an already-rectified
        # depth grid a second time. This policy applies to the exact known model
        # and this source's native Y16 stream (SDK alignment is not enabled).
        if model == 'Orbbec Gemini 2':
            calibration['factory_distortion']=list(calibration['distortion'])
            calibration['factory_distortion_model']=calibration['distortion_model']
            calibration['distortion']=[0.]*8
            calibration['distortion_model']='none'
            calibration['effective_distortion_provenance']={
                'source':'https://github.com/orbbec/OrbbecSDK_v2/blob/main/docs/tutorial/orbbec_camera_distortion.md',
                'policy':'Gemini 2 native depth is rectified; SDK alignment disabled',
                'hardware_verified':False}
        return calibration

    @staticmethod
    def _extrinsic(ext):
        t=np.eye(4)
        t[:3,:3]=np.asarray(ext.rot,dtype=float).reshape(3,3)
        t[:3,3]=np.asarray(ext.transform,dtype=float)*.001
        return t.tolist()

    def _properties(self):
        result={}
        for name in ('OB_PROP_COLOR_AUTO_EXPOSURE_BOOL','OB_PROP_COLOR_EXPOSURE_INT',
                     'OB_PROP_DEPTH_AUTO_EXPOSURE_BOOL','OB_PROP_DEPTH_EXPOSURE_INT',
                     'OB_PROP_MIN_DEPTH_INT','OB_PROP_MAX_DEPTH_INT',
                     'OB_PROP_DEPTH_SOFT_FILTER_BOOL','OB_PROP_DEPTH_POSTFILTER_BOOL'):
            try:
                prop=getattr(self.sdk.OBPropertyID,name)
                if not self.device.is_property_supported(prop,self.sdk.OBPermissionType.PERMISSION_READ):
                    result[name]={'status':'unsupported'}
                else:
                    getter=self.device.get_bool_property if name.endswith('BOOL') else self.device.get_int_property
                    result[name]={'status':'read','value':getter(prop),'unit':'SDK property native; see SDK docs'}
            except Exception as e:
                result[name]={'status':'unavailable','reason':str(e)}
        return result

    def _start_imu(self,depth_profile):
        enabled=[]
        for stream,sensor_type in [('accel',self.sdk.OBSensorType.ACCEL_SENSOR),('gyro',self.sdk.OBSensorType.GYRO_SENSOR)]:
            try:
                sensor=self.device.get_sensor(sensor_type)
                profile=sensor.get_stream_profile_list().get_stream_profile_by_index(0)
            except Exception as e:
                self.metadata['imu'][stream]={'status':'unsupported','reason':str(e)}
                continue
            # sensor callbacks operate at the IMU's selected native rate, independent of video.
            try:
                ext=profile.get_extrinsic_to(depth_profile)
                self.calibration['T_depth_from_'+stream]=self._extrinsic(ext)
            except Exception as e:
                self.calibration['T_depth_from_'+stream]=None
                self.metadata['imu'][stream+'_extrinsic_error']=str(e)
            sensor.start(profile,lambda frame,s=stream:self._on_imu(s,frame))
            self.imu_sensors.append(sensor)
            enabled.append(stream)
            self.metadata['imu'][stream]={'status':'enabled','profile':str(profile)}
        self.metadata['imu']['enabled']=bool(enabled)
        self.metadata['imu']['enabled_streams']=enabled

    def _on_imu(self,stream,frame):
        try:
            typed=frame.as_accel_frame() if stream=='accel' else frame.as_gyro_frame()
            value=typed.get_value()
            sample=self._sample(stream,typed,np.array([value.x,value.y,value.z],dtype=np.float64))
            self._queue.put_nowait(sample)
        except queue.Full:
            self._fatal=RuntimeError('IMU raw queue overflow; capture stopped to avoid silent sample loss')
        except Exception as e:
            self._fatal=e

    def _sample(self,stream,frame,data,scale=None):
        timestamp=int(frame.get_timestamp_us())
        return Sample(stream,np.array(data,copy=True),int(frame.get_index()),timestamp,'us','orbbec_device',
                      time.monotonic_ns(),timestamp-self._origin_us,scale)

    def _video(self,stream,frame):
        if frame is None:
            return None
        index=int(frame.get_index())
        # A frameset can include a repeated cached frame; keep every original only once.
        if self._last_ids.get(stream)==index:
            return None
        self._last_ids[stream]=index
        shape=(int(frame.get_height()),int(frame.get_width()))
        dtype=np.uint16 if stream=='depth' else np.uint8
        data=np.frombuffer(frame.get_data(),dtype=dtype).reshape(shape if stream=='depth' else shape+(3,)).copy()
        scale=float(frame.get_depth_scale())*.001 if stream=='depth' else None
        if scale is not None and (not np.isfinite(scale) or scale<=0):
            raise RuntimeError('SDK returned invalid depth scale')
        return self._sample(stream,frame,data,scale)

    def captures(self,stop_event):
        last_video=time.monotonic()
        timeout=float(self.config.get('timeout_seconds',5))
        while not stop_event.is_set():
            if self._fatal is not None:
                raise self._fatal
            frames=self.pipeline.wait_for_frames(100)
            imu=[]
            # Bound work per iteration as well as queue capacity.
            for _ in range(self._queue.maxsize):
                try:
                    imu.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            color=depth=None
            if frames is not None:
                color=self._video('color',frames.get_color_frame())
                depth=self._video('depth',frames.get_depth_frame())
                if color is not None or depth is not None:
                    last_video=time.monotonic()
            if time.monotonic()-last_video>timeout:
                raise RuntimeError('Orbbec camera disconnected or video timeout')
            if color is not None or depth is not None or imu:
                yield Capture(color,depth,imu)
        # Stop producers before draining all remaining raw IMU samples.
        self._stop_imu()
        imu=[]
        while not self._queue.empty():
            imu.append(self._queue.get_nowait())
        if imu:
            yield Capture(imu=imu)
        # A callback can fail while wait_for_frames is blocked or exactly when
        # stop is requested. A stopped loop must still surface that lost sample.
        if self._fatal is not None:
            raise self._fatal

    def _stop_imu(self):
        for sensor in self.imu_sensors:
            try:
                sensor.stop()
            except Exception:
                pass
        self.imu_sensors=[]

    def close(self):
        self._stop_imu()
        if self.pipeline is not None and getattr(self,'_running',False):
            try:
                self.pipeline.stop()
            finally:
                self._running=False


def make_source(config):
    source=_settings(config)
    kind=source.get('kind','synthetic')
    if kind=='synthetic':
        return SyntheticSource(config)
    if kind=='replay':
        if not source.get('path'):
            raise ValueError('replay source.path is required')
        return ReplaySource(source['path'],config)
    if kind=='orbbec':
        return OrbbecSource(config)
    raise ValueError(f'unsupported source kind: {kind}')
