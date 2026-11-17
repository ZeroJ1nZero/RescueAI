import json
import threading

import h5py
import numpy as np
import pytest

from fire_vision.spatial.sources import SyntheticSource, ReplaySource, OrbbecSource, make_source


def test_synthetic_raw_scales_imu_rates_and_owned_buffers():
    source = SyntheticSource({'source': {'frames': 4, 'fps': 10, 'depth_scale_m': 0.0005}})
    source.open()
    frames = list(source.captures(threading.Event()))
    assert source.metadata['synthetic'] is True
    assert len(frames) == 4
    assert frames[0].depth.data.dtype == np.uint16
    assert frames[0].color.data.dtype == np.uint8
    assert frames[0].depth.depth_scale_m == 0.0005
    assert np.median(frames[0].depth.data[frames[0].depth.data > 0]) * 0.0005 == pytest.approx(2.0)
    assert frames[0].depth.sensor_timestamp > 0
    assert frames[0].color.sensor_timestamp != frames[0].depth.sensor_timestamp
    assert len([s for f in frames for s in f.imu if s.stream == 'accel']) > len(frames)
    assert frames[0].synthetic_pose is not None
    original = frames[1].depth.data.copy()
    frames[0].depth.data[:] = 99
    np.testing.assert_array_equal(frames[1].depth.data, original)


def test_synthetic_stop_does_not_emit_another_frame():
    source = SyntheticSource({'source': {'frames': 20}})
    source.open()
    stop = threading.Event()
    iterator = source.captures(stop)
    next(iterator)
    stop.set()
    assert list(iterator) == []


def write_session(path):
    with h5py.File(path, 'w') as h:
        h.create_dataset('/meta/json', data=json.dumps({'synthetic': False, 'device': 'fixture'}))
        h.create_dataset('/calibration/json', data=json.dumps({'test_calibration': 4}))
        for stream, times, data in [
            ('color', [0, 100_000], np.arange(2*4*5*3, dtype=np.uint8).reshape(2,4,5,3)),
            ('depth', [2_000, 102_000, 202_000], np.arange(3*4*5, dtype=np.uint16).reshape(3,4,5)),
            ('imu/accel', [1_000, 30_000, 70_000], np.arange(9, dtype=np.float64).reshape(3,3)),
            ('imu/gyro', [3_000, 33_000], np.arange(6, dtype=np.float64).reshape(2,3)),
        ]:
            g = h.require_group('/raw/'+stream)
            g.create_dataset('data', data=data)
            g.create_dataset('time_us', data=np.array(times,dtype=np.int64))
            g.create_dataset('frame_id', data=np.arange(len(times),dtype=np.int64)+30)
            g.create_dataset('sensor_timestamp', data=np.array(times,dtype=np.int64)+1_000_000)
            g.create_dataset('host_monotonic_ns', data=np.array(times,dtype=np.int64)*1000+5_000_000)
            g.attrs['timestamp_unit']='us'
            g.attrs['clock']='device_test'
            if stream == 'depth':
                g.create_dataset('depth_scale_m',data=np.array([.0003,.0004,.0005]))


def test_replay_preserves_independent_streams_and_original_times(tmp_path):
    path=tmp_path/'session.h5'
    write_session(path)
    source=ReplaySource(path, {})
    source.open()
    captures=list(source.captures(threading.Event()))
    source.close()
    assert source.metadata['synthetic'] is False
    assert source.calibration == {'test_calibration':4}
    assert source.metadata['replay']['source_path'] == str(path.resolve())
    for stream in ['color','depth','accel','gyro']:
        samples=[s for c in captures for s in ([c.color,c.depth]+c.imu) if s and s.stream==stream]
        with h5py.File(path) as h:
            g=h['/raw/'+('imu/' if stream in ('accel','gyro') else '')+stream]
            assert len(samples)==len(g['data'])
            for i,sample in enumerate(samples):
                np.testing.assert_array_equal(sample.data,g['data'][i])
                assert sample.time_us==g['time_us'][i]
                assert sample.sensor_timestamp==g['sensor_timestamp'][i]
                assert sample.frame_id==g['frame_id'][i]
                assert sample.clock=='device_test'
                if stream=='depth': assert sample.depth_scale_m==g['depth_scale_m'][i]


def test_replay_does_not_relabel_real_pose_as_synthetic(tmp_path):
    path=tmp_path/'session.h5'
    write_session(path)
    with h5py.File(path,'a') as h:
        h.create_dataset('/derived/poses/matrices',data=np.tile(np.eye(4),(3,1,1)))
    source=ReplaySource(path,{})
    source.open()
    assert all(c.synthetic_pose is None for c in source.captures(threading.Event()))
    source.close()


def test_sdk_missing_fails_explicitly_without_fabricated_frames():
    import importlib.util
    if importlib.util.find_spec('pyorbbecsdk'):
        pytest.skip('SDK installed')
    with pytest.raises(RuntimeError,match='pyorbbecsdk'):
        OrbbecSource({}).open()


def test_factory_rejects_unknown_source():
    with pytest.raises(ValueError,match='source'):
        make_source({'source':{'kind':'not_a_camera'}})


def test_sdk_buffer_copy_and_scale_are_independent_of_frame_lifetime():
    class DepthFrame:
        buffer = np.array([[0,2000],[4000,6000]],np.uint16)
        def get_index(self): return 1
        def get_timestamp_us(self): return 1234
        def get_height(self): return 2
        def get_width(self): return 2
        def get_data(self): return self.buffer
        def get_depth_scale(self): return .5  # SDK unit is millimeters / raw unit
    source=OrbbecSource({})
    source._origin_us=1200
    frame=DepthFrame()
    sample=source._video('depth',frame)
    frame.buffer[:]=0
    np.testing.assert_array_equal(sample.data,[[0,2000],[4000,6000]])
    assert sample.depth_scale_m==.0005
    assert sample.time_us==34
    assert sample.sensor_timestamp==1234


def test_imu_raw_overflow_is_fatal_and_never_unbounded():
    from types import SimpleNamespace
    class ImuFrame:
        def as_accel_frame(self): return self
        def get_value(self): return SimpleNamespace(x=1.,y=2.,z=3.)
        def get_timestamp_us(self): return 1234
        def get_index(self): return 1
    source=OrbbecSource({'source':{'imu_queue_size':1}})
    source._origin_us=1200
    source._on_imu('accel',ImuFrame())
    source._on_imu('accel',ImuFrame())
    assert source._queue.qsize()==1
    assert isinstance(source._fatal,RuntimeError)
    assert 'overflow' in str(source._fatal)
    stopped=threading.Event(); stopped.set()
    with pytest.raises(RuntimeError,match='overflow'):
        list(source.captures(stopped))
    with pytest.raises(ValueError,match='queue'):
        OrbbecSource({'source':{'imu_queue_size':0}})


def test_synthetic_pose_roundtrip_is_only_enabled_for_synthetic_origin(tmp_path):
    path=tmp_path/'session.h5'
    write_session(path)
    poses=np.tile(np.eye(4),(3,1,1))
    poses[1,0,3]=.25
    with h5py.File(path,'a') as h:
        del h['/meta/json']
        h.create_dataset('/meta/json',data=json.dumps({'synthetic':True}))
        h.create_dataset('/raw/synthetic_poses',data=poses)
    source=ReplaySource(path,{})
    source.open()
    frames=list(source.captures(threading.Event()))
    source.close()
    depth=[c for c in frames if c.depth is not None]
    assert len(depth)==3
    np.testing.assert_array_equal(depth[1].synthetic_pose,poses[1])
