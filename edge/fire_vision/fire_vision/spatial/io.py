"""GPIO is optional; pin numbering and wiring are operator configuration."""
import logging


class StatusLED:
    def set_state(self,state):
        logging.info("state=%s",state)

    def close(self):
        pass


class JetsonGPIO:
    def __init__(self,config,on_press):
        import Jetson.GPIO as GPIO
        self.gpio,self.config=GPIO,config
        self.button=config.get("button_pin")
        self.led=config.get("led_pin")
        if self.button is None:
            raise ValueError("gpio.button_pin must be explicitly configured")
        mode=config.get("mode","BOARD")
        if mode not in ("BOARD","BCM"):
            raise ValueError("gpio.mode must be BOARD or BCM")
        GPIO.setmode(getattr(GPIO,mode))
        pull=config.get("pull","UP")
        if pull not in ("UP","DOWN"):
            raise ValueError("gpio.pull must be UP or DOWN")
        GPIO.setup(self.button,GPIO.IN,pull_up_down=getattr(GPIO,"PUD_"+pull))
        if self.led is not None: GPIO.setup(self.led,GPIO.OUT,initial=GPIO.LOW)
        edge=GPIO.FALLING if pull=="UP" else GPIO.RISING
        GPIO.add_event_detect(self.button,edge,callback=lambda channel:on_press(),
                              bouncetime=int(config.get("debounce_ms",250)))

    def set_state(self,state):
        if self.led is not None:
            self.gpio.output(self.led,self.gpio.HIGH if state in ("READY","DONE") else self.gpio.LOW)

    def close(self):
        self.gpio.remove_event_detect(self.button)
        pins=[self.button]+([self.led] if self.led is not None else [])
        self.gpio.cleanup(pins)
