"""Standalone collector/service commands, integrated into fire-vision spatial."""
import argparse
from copy import deepcopy
import json
import logging
from pathlib import Path
import select
import signal
import sys
import threading
import time

from .controller import SessionController
from .io import JetsonGPIO
from .reader import Reader
from .storage import strict_json


def load_config(path):
    with Path(path).open(encoding="utf-8") as f:
        c=json.load(f,parse_constant=lambda v: (_ for _ in ()).throw(ValueError("nonfinite config value")))
    if not isinstance(c,dict) or not isinstance(c.get("source"),dict) or not isinstance(c.get("storage"),dict):
        raise ValueError("source and storage configuration objects required")
    if not c["storage"].get("path"):
        raise ValueError("storage.path required")
    # Paths are resolved relative to config, not systemd's working directory.
    root=Path(path).resolve().parent
    for group,key in (("storage","path"),("storage","mount_path"),("source","path"),("detector","model")):
        value=c.get(group,{}).get(key)
        if value:
            c[group][key]=str((root/Path(value).expanduser()).resolve())
    return c


def main(argv=None):
    parser=argparse.ArgumentParser(description="Spatial raw capture and versioned analysis")
    sub=parser.add_subparsers(dest="command",required=True)
    for name in ("record","serve","replay"):
        p=sub.add_parser(name)
        p.add_argument("--config",required=True)
        if name=="record": p.add_argument("--duration",type=float)
        if name=="replay": p.add_argument("input")
    inspect=sub.add_parser("inspect")
    inspect.add_argument("map")
    args=parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    controller=None
    old_signals={}
    timer=None
    quit_event=threading.Event()
    try:
        if args.command=="inspect":
            with Reader(args.map) as r:
                print(strict_json({"session_id":r.manifest["session_id"],"status":r.manifest["status"],
                      "synthetic":r.manifest["synthetic"],"objects":r.objects(),"features":r.manifest["features"],
                      "raw_color_frames":len(r.h5["raw/color/time_us"]),"raw_depth_frames":len(r.h5["raw/depth/time_us"]),
                      "surface_points":len(r.h5["map/points/positions"]),"quality":r.manifest["quality"]}))
            return 0
        config=load_config(args.config)
        if args.command=="replay":
            config=deepcopy(config)
            config["source"]={"kind":"replay","path":str(Path(args.input).resolve()),"realtime":False}
        if args.command=="record" and args.duration is not None and args.duration<=0:
            raise ValueError("duration must be positive")
        controller=SessionController(config)
        def shutdown(signum,frame):
            quit_event.set()
            controller.request_shutdown()
        for signum in (signal.SIGINT,signal.SIGTERM):
            old_signals[signum]=signal.signal(signum,shutdown)
        if config.get("gpio",{}).get("backend","none")=="jetson":
            controller.led=JetsonGPIO(config["gpio"],controller.press)
        elif config.get("gpio",{}).get("backend","none")!="none":
            raise ValueError("gpio.backend must be none or jetson")
        controller.prepare()
        print(strict_json(controller.status()),flush=True)
        if quit_event.is_set(): return 0
        if args.command in ("record","replay"):
            if not controller.start(): return 0 if quit_event.is_set() else 2
            if getattr(args,"duration",None):
                timer=threading.Timer(args.duration,controller.stop)
                timer.daemon=True; timer.start()
            while controller.thread.is_alive(): controller.wait(.2)
            print(strict_json(controller.status()),flush=True)
            return 0 if controller.state=="DONE" else 2
        stdin_open=True
        while not quit_event.is_set():
            if stdin_open:
                readable,_,_=select.select([sys.stdin],[],[],.2)
                if readable:
                    line=sys.stdin.readline()
                    if not line:
                        stdin_open=False
                        continue
                    command=line.strip().lower()
                    if command=="start": controller.start()
                    elif command=="stop": controller.stop()
                    elif command=="press": controller.press()
                    elif command=="quit": quit_event.set(); controller.stop()
                    elif command not in ("status",""): logging.error("commands: start stop press status quit")
                    print(strict_json(controller.status()),flush=True)
            else:
                quit_event.wait(.2)
        controller.wait()
        return 2 if controller.state=="ERROR" else 0
    except Exception as exc:
        logging.error("%s: %s",type(exc).__name__,exc)
        return 2
    finally:
        if timer is not None: timer.cancel()
        if controller is not None: controller.close()
        for signum,handler in old_signals.items(): signal.signal(signum,handler)


if __name__=="__main__":
    raise SystemExit(main())
