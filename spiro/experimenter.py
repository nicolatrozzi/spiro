# experimenter.py -
#   this file handles running the actual experiments
#

import os
import time
import threading
import numpy as np
from PIL import Image
from io import BytesIO
from datetime import date
from statistics import mean
from collections import deque
from spiro.config import Config
from spiro.logger import log, debug

class Experimenter(threading.Thread):
    def __init__(self, hw=None, cam=None):
        """Initialize the experimenter with hardware and camera configurations."""
        super().__init__()
        self.hw = hw
        self.cam = cam
        if self.cam is None:
            raise ValueError("Camera is not initialized!")
        
        self.cfg = Config()
        self._initialize_defaults()

    def _initialize_defaults(self):
        """Set the default parameters for the experimenter."""
        self.delay = 60
        self.duration = 7
        self.dir = os.path.expanduser('~')
        self.starttime = 0
        self.endtime = 0
        self.running = False
        self.status = "Stopped"
        self.daytime = "TBD"
        self.quit = False
        self.stop_experiment = False
        self.status_change = threading.Event()
        self.next_status = ''
        self.last_captured = [''] * 4
        self.preview = [''] * 4
        self.preview_lock = threading.Lock()
        self.nshots = 0
        self.idlepos = 0

    def stop(self):
        """Stop the current experiment."""
        self.status = "Stopping"
        self.next_status = ''
        self.stop_experiment = True
        log("Stopping running experiment...")

    def getDefName(self):
        """Return a default experiment name."""
        today = date.today().strftime('%Y.%m.%d')
        return today + ' ' + self.cfg.get('name')

    def temporary_resolution(self, resolution):
        """Temporarily set the camera resolution."""
        oldres = self.cam.resolution
        self.cam.resolution = resolution
        yield
        self.cam.resolution = oldres

    def isDaytime(self):
        """Determine if it's daytime based on average pixel intensity."""
        with self.temporary_resolution((320, 240)):
            self._set_daytime_camera_settings()
            output = np.empty((240, 320, 3), dtype=np.uint8)
            self.cam.capture(output, 'rgb')
            debug("Daytime estimation mean value: " + str(output.mean()))
        if self.cam.type != 'legacy':
            self.cam.shutter_speed = 1000000 // self.cfg.get('dayshutter')
            output = self.cam.camera.capture_array('lores')
            debug("Daytime estimation mean value: " + str(output.mean()))
        return output.mean() > 10

    def _set_daytime_camera_settings(self):
        """Set camera settings for daytime estimation."""
        self.cam.iso = self.cfg.get('dayiso')
        self.cam.shutter_speed = 1000000 // self.cfg.get('dayshutter')

    def setWB(self):
        """Determine and set the white balance for the camera."""
        debug("Determining white balance.")
        self.cam.awb_mode = "auto"
        time.sleep(2)
        g = self.cam.awb_gains
        self.cam.awb_mode = "off"
        self.cam.awb_gains = g
        
    def takePicture(self, name, plate_no):
        """Capture an image based on the time of day."""
        stream = BytesIO()
        prev_daytime = self.daytime
        self.daytime = self.isDaytime()

        self._set_camera_settings_based_on_time_of_day()

        if prev_daytime != self.daytime and self.daytime and self.cam.awb_mode != "off":
            self.setWB()

        self._capture_and_save_image(name, plate_no, stream)

    def _set_camera_settings_based_on_time_of_day(self):
        """Set camera settings based on whether it's day or night."""
        time.sleep(0.5)
        if self.daytime:
            self.cam.shutter_speed = 1000000 // self.cfg.get('dayshutter')
            self.cam.iso = self.cfg.get('dayiso')
            self.cam.color_effects = None
        else:
            self.hw.LEDControl(True)  # turn on led
            time.sleep(0.5)
            self.cam.shutter_speed = 1000000 // self.cfg.get('nightshutter')
            self.cam.iso = self.cfg.get('nightiso')

    def _capture_and_save_image(self, name, plate_no, stream):
        """Capture the image and save it."""
        debug(f"Capturing {name}.")
        self.cam.exposure_mode = "off"

        # Capture based on camera type
        if self.cam.type == 'legacy':
            self.cam.capture(stream, format='rgb')
        else:
            stream.write(self.cam.camera.capture_array('main'))

        # Turn off LED immediately after capture if it's nighttime
        if not self.daytime:
            self.hw.LEDControl(False)

        self._process_and_save_captured_image(name, plate_no, stream)

    def _process_and_save_captured_image(self, name, plate_no, stream):
        """Process the captured image stream and save it."""
        raw_res = self._get_raw_resolution()
        stream.seek(0)
        im = Image.frombytes('RGB', raw_res, stream.read()).crop(box=(0, 0) + self.cam.resolution)
        
        if not os.path.exists(self.dir):
            os.makedirs(self.dir)

        im.save(os.path.join(self.dir, name))
        self._create_thumbnail_preview(im, plate_no)
        im.close()

    def _create_thumbnail_preview(self, im, plate_no):
        """Create a thumbnail preview of the image."""
        im.thumbnail((800, 600))
        try:
            self.preview_lock.acquire()
            self.preview[plate_no] = BytesIO()
            im.save(self.preview[plate_no], format="jpeg")
        finally:
            self.preview_lock.release()
        
    def run(self):
        """Starts the experiment if there's a signal to do so."""
        while not self.quit:
            self.status_change.wait()
            if self.next_status == 'run':
                self.next_status = ''
                self.status_change.clear()
                self.runExperiment()

    def go(self):
        """Signals intent to start the experiment."""
        self.next_status = 'run'
        self.status_change.set()
        
    def runExperiment(self):
        """The main experiment loop."""
        if self.running:
            raise RuntimeError('An experiment is already running.')

        try:
            debug("Starting experiment.")
            self.cam.still_mode() 
            self.running = True
            self.status = "Initiating"
            self.starttime = time.time()
            self.endtime = time.time() + 60 * 60 * 24 * self.duration
            self.last_captured = [''] * 4
            self.delay = self.delay or 0.001
            self.nshots = self.duration * 24 * 60 // self.delay
            self.cam.exposure_mode = "auto"
            self.cam.shutter_speed = 0
            self.hw.LEDControl(False)

            if self.dir == os.path.expanduser('~'):
                self.dir = os.path.join(os.path.expanduser('~'), self.getDefName())

            for i in range(4):
                platedir = "plate" + str(i + 1)
                os.makedirs(os.path.join(self.dir, platedir), exist_ok=True)

            while time.time() < self.endtime and not self.stop_experiment:
                loopstart = time.time()
                nextloop = time.time() + 60 * self.delay
                if nextloop > self.endtime:
                    nextloop = self.endtime
                
                for i in range(4):
                    if i == 0:
                        self.hw.motorOn(True)
                        self.status = "Finding start position"
                        debug("Finding initial position.")
                        self.hw.findStart(calibration=self.cfg.get('calibration'))
                        debug("Found initial position.")
                        if self.status != "Stopping": self.status = "Imaging"
                    else:
                        debug("Rotating stage.")
                        self.hw.halfStep(100, 0.03)

                    time.sleep(0.5)

                    now = time.strftime("%Y%m%d-%H%M%S", time.localtime())
                    name = os.path.join("plate" + str(i + 1), "plate" + str(i + 1) + "-" + now)
                    self.takePicture(name, i)

                self.nshots -= 1
                self.hw.motorOn(False)
                if self.status != "Stopping": self.status = "Waiting"

                if self.idlepos > 0:
                    self.hw.motorOn(True)
                    self.hw.halfStep(50 * self.idlepos, 0.03)
                    self.hw.motorOn(False)

                self.idlepos += 1
                if self.idlepos > 7:
                    self.idlepos = 0

                while time.time() < nextloop and not self.stop_experiment:
                    time.sleep(1)

        finally:
            self._end_experiment()

    def _start_experiment(self):
        """Setup procedures to start the experiment."""
        # Original logic or any setup procedures you intend to have
        pass

    def _experiment_iteration(self):
        """One iteration in the main experiment loop."""
        # Original logic for one iteration in the main experiment loop
        pass

    def _end_experiment(self):
        """Cleanup procedures after the experiment ends."""
        log("Experiment stopped.")
        self.cam.color_effects = None
        self.status = "Stopped"
        self.stop_experiment = False
        self.running = False
        self.cam.exposure_mode = "auto"
        self.cam.meter_mode = 'spot'
        
        
