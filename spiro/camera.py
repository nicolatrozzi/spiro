import time
from spiro.logger import log, debug

try:
    from picamera2 import Picamera2
    from picamera2.outputs import FileOutput
    from picamera2.encoders import MJPEGEncoder
    from libcamera import controls
except ImportError as e:
    print(f"Error: {e}")
    print("Picamera2 (for libcamera) module is missing. Please install the appropriate module.")
    exit()  # Exit the script if the necessary modules are missing

class NewCamera:
    def __init__(self):
        debug('Libcamera detected.')
        self.camera = Picamera2()
        self.type = 'libcamera'
        self.streaming = False
        self.stream_output = None
        self.still_config = self.camera.create_still_configuration(main={"size": (1920, 1080)}, lores={"size": (1920, 1080)})
        self.video_config = self.camera.create_video_configuration(main={"size": (1200, 1000)})
        self.camera.configure(self.video_config)
        
         # Define the default scaler crop as the full resolution
        self._zoom = {
            "x": 0,
            "y": 0,
            "w": 1,  # This signifies the full width
            "h": 1   # This signifies the full height
        }
    
        # Print the available keys in camera_controls
        print("Available keys in camera_controls:", self.camera.camera_controls.keys())

        # Check if LensPosition is available
        if 'LensPosition' in self.camera.camera_controls:
            self.lens_limits = self.camera.camera_controls['LensPosition']
        else:
            self.lens_limits = None
            print("LensPosition control not available for this camera.")
      
        # Create a dictionary for controls you want to set
        control_values = {
            'NoiseReductionMode': controls.draft.NoiseReductionModeEnum.Off,
            'AeMeteringMode': controls.AeMeteringModeEnum.Spot,
            "AfMode": controls.AfModeEnum.Manual
            }

        # Set only available controls
        available_controls = set(self.camera.camera_controls.keys())
        controls_to_set = {k: v for k, v in control_values.items() if k in available_controls}

        # Apply the controls
        self.camera.set_controls(controls_to_set)

        self.camera.start()

    def start_stream(self, output):
        log('Starting stream.')
        try:
            self.stream_output = output
            self.streaming = True
            self.camera.switch_mode(self.video_config)
            self.camera.start_recording(MJPEGEncoder(), FileOutput(output))
        except:
            pass

    def stop_stream(self):
        # we do not want to stop the stream on libcamera, since it can switch modes without doing so.
        pass

    @property
    def zoom(self):
        return self._zoom

    @zoom.setter
    def zoom(self, value):
        x, y, w, h = value
        self.set_zoom(x, y, w, h)

    def set_zoom(self, x, y, w, h):
        self._zoom = {
            "x": x,
            "y": y,
            "w": w,
            "h": h
        }

        (resx, resy) = self.camera.camera_properties['PixelArraySize']
        self.camera.set_controls({
            "ScalerCrop": (int(x * resx), int(y * resy), int(w * resx), int(h * resy))
        })

    
    def auto_exposure(self, value):
        self.camera.set_controls({'AeEnable': value})

    def capture(self, obj, format='png'):
        stream = self.streaming

        log('Capturing image.')
        self.camera.switch_mode(self.still_config)
        self.camera.capture_file(obj, format=format)
        log('Ok.')

        if stream:
            self.start_stream(self.stream_output)

    @property
    def shutter_speed(self):
        return self.camera.capture_metadata()['ExposureTime']
    
    @shutter_speed.setter
    def shutter_speed(self, value):
        self.camera.set_controls({"ExposureTime": value})

    @property
    def iso(self):
        return int(self.camera.capture_metadata()['AnalogueGain'] * 100)
    
    @iso.setter
    def iso(self, value):
        self.camera.set_controls({"AnalogueGain": value / 100})

    def close(self):
        self.camera.close()

    def still_mode(self):
        self.camera.switch_mode(self.still_config)

    def video_mode(self):
        self.camera.switch_mode(self.video_config)

    @property
    def resolution(self):
        # XXX
        return (1920, 1600)

    @resolution.setter
    def resolution(self, res):
        # XXX
        pass

    @property
    def awb_mode(self):
        # XXX: not implemented
        pass
    
    @awb_mode.setter
    def awb_mode(self, mode):
        # XXX: not implemented
        pass

    @property
    def awb_gains(self):
        # XXX: not implemented
        pass
    
    @awb_gains.setter
    def awb_gains(self, gains):
        # XXX: not implemented
        pass
    
    def focus(self, val):
        if 'LensPosition' in self.camera.camera_controls:
            self.camera.set_controls({'LensPosition': val})
        else:
            print("LensPosition control not available for this camera.")
            # Handle the error or do nothing

cam = NewCamera()
