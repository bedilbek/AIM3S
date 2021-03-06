import cv2
import numpy as np
import argparse
import pytz
import os
from enum import Enum
from datetime import datetime
from dateutil import parser as dateparser

# Python 2-3 compatibility
import sys
if sys.version_info.major < 3:
    input = raw_input


# Aux constants & enums
DEFAULT_TIMEZONE = pytz.timezone('America/Los_Angeles')
DATETIME_STR_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
EXPERIMENT_DATETIME_STR_FORMAT = "%Y-%m-%d_%H-%M-%S"

class JointEnum(Enum):
    NOSE = 0
    NECK = 1
    RSHOULDER = 2
    RELBOW = 3
    RWRIST = 4
    LSHOULDER = 5
    LELBOW = 6
    LWRIST = 7
    MIDHIP = 8
    RHIP = 9
    RKNEE = 10
    RANKLE = 11
    LHIP = 12
    LKNEE = 13
    LANKLE = 14
    REYE = 15
    LEYE = 16
    REAR = 17
    LEAR = 18
    LBIGTOE = 19
    LSMALLTOE = 20
    LHEEL = 21
    RBIGTOE = 22
    RSMALLTOE = 23
    RHEEL = 24
    BACKGND = 25


# Aux functions
def str2bool(s):
    return s.lower() not in {"no", "false", "n", "f", "0"}

def _min(a, b):
    return a if a < b else b

def _max(a, b):
    return a if a > b else b

def ensure_folder_exists(folder):
    try:
        os.makedirs(folder)
    except OSError:  # Already exists -> Ignore
        pass

def list_subfolders(folder, do_sort=False):
    subfolders = next(os.walk(folder))[1]
    return subfolders if not do_sort else sorted(subfolders)

def format_axis_as_timedelta(axis):  # E.g. axis=ax.xaxis
    from matplotlib import pyplot as plt
    from datetime import timedelta

    def timedelta2str(td):
        is_negative = (td.total_seconds() < 0)
        s = str(td if not is_negative else -td)  # str(td) prints "-1 day, 23:59:59" if td=-1s -> Print "0:01" instead
        if s.startswith("0:"): s = s[2:]  # Remove hours if hours=0
        if is_negative: s = '-' + s  # Add the '-' sign if needed
        return s

    axis.set_major_formatter(plt.FuncFormatter(lambda x, pos: timedelta2str(timedelta(seconds=x))))

def get_nonempty_input(msg):
    out = ""
    while len(out) < 1:
        out = input(msg)
    return out

def date_range(t_start, t_end, t_delta):
    if t_delta.total_seconds() == 0:
        raise Exception("Infinite loop!! t_delta can't be 0 (are you dividing two ints?)")

    t = t_start
    while t < t_end:
        yield t
        t += t_delta

def time_to_float(t_arr, t_ref=None):
    if t_ref is None: t_ref = t_arr[0]
    return [(t-t_ref).total_seconds() for t in t_arr]

def save_datetime_to_h5(t_arr, h5_handle, field_name):
    h5_handle.create_dataset(field_name, data=[(t-t_arr[0]).total_seconds() for t in t_arr])
    h5_handle.create_dataset(field_name + "_str", data=[str(t).encode('utf8') for t in t_arr])

def str_to_datetime(str_dt, tz=DEFAULT_TIMEZONE):
    t = dateparser.parse(str_dt.decode('utf8'))
    return tz.localize(t) if tz is not None and t.tzinfo is None else t

def plt_fig_to_cv2_img(fig):
    img = np.frombuffer(fig.canvas.tostring_rgb(), dtype=np.uint8)
    img = img.reshape(fig.canvas.get_width_height()[::-1] + (3,))
    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)  # img is rgb, convert to opencv's default bgr

    return img


# Aux helper classes
class ExperimentTraverser:
    def __init__(self, main_folder, start_datetime=datetime.min, end_datetime=datetime.max):
        self.main_folder = main_folder
        self.start_datetime = start_datetime
        self.end_datetime = end_datetime

    def process_subfolder(self, f):
        pass  # Implement in subclass

    def on_done(self):
        pass  # Implement in subclass

    def run(self):
        for f in list_subfolders(self.main_folder, True):
            if f.endswith("_ignore"): continue
            try:
                t = datetime.strptime(f, EXPERIMENT_DATETIME_STR_FORMAT)  # Folder name specifies the date -> Convert to datetime
            except:
                print("Can't parse the name of this folder: '{}'. Skipping...".format(f))
                continue

            # Filter by experiment date (only consider experiments within t_start and t_end)
            if self.start_datetime <= t <= self.end_datetime:
                self.process_subfolder(f)

        self.on_done()


class HSVthreshHelper:
    WIN_NAME = "HSV thresholding aux tool"
    PIXEL_INFO_RADIUS = 3
    PIXEL_INFO_COLOR = (255, 0, 0)
    PIXEL_INFO_THICKNESS = 2

    def __init__(self, input):
        self.input = input
        self.H_min = 0
        self.H_max = 179
        self.S_min = 0
        self.S_max = 255
        self.V_min = 0
        self.V_max = 255
        self.is_playing = True  # Play/pause for videos/streams
        self.pixel = (0, 0)
        self.show_pixel_info = True

    def get_str_lims(self):
        return "H: {}-{}, S: {}-{}, V: {}-{}".format(self.H_min, self.H_max, self.S_min, self.S_max, self.V_min, self.V_max)

    def on_click(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN or (event == cv2.EVENT_MOUSEMOVE and flags&cv2.EVENT_FLAG_LBUTTON):
            self.pixel = (x, y)
            self.show_pixel_info = True
        elif event == cv2.EVENT_RBUTTONDOWN:
            self.show_pixel_info = False

    def run(self):
        # Input could be an image, a camera id, or a video/IP cam. Figure out which one.
        img = cv2.imread(self.input)  # Try opening input as an image
        is_video = (img is None)  # If it didn't work, then input is a video
        if is_video:
            try:  # Try to convert input to int (camera number)
                self.input = int(self.input)
            except ValueError:
                pass  # Input is a video or an IP cam, nothing to do
            video = cv2.VideoCapture(self.input)
        else:
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # Create a window with 6 sliders (HSV min and max)
        cv2.namedWindow(self.WIN_NAME)
        lims = (179, 255, 255)
        for i_hsv, hsv in enumerate("HSV"):
            for minmax in ("min", "max"):
                name = hsv + '_' + minmax  # e.g. H_min
                cv2.createTrackbar(name, self.WIN_NAME, getattr(self, name), lims[i_hsv]-1 if minmax=="min" else lims[i_hsv], lambda v, what=name: setattr(self, what, v))
        cv2.setMouseCallback(self.WIN_NAME, self.on_click)

        while True:
            # Read next frame if it's a video and we haven't hit pause
            if is_video and self.is_playing:
                ok, img = video.read()
                if not ok:  # Made it to the end of the video, loop back
                    video = cv2.VideoCapture(self.input)
                    ok, img = video.read()
                hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            pixel_hsv = hsv[self.pixel[1], self.pixel[0], :]

            # Threshold the HSV image
            h_offset = self.H_max+1 if self.H_min > self.H_max else 0
            hsv_offset = np.mod(hsv[:,:,0] - h_offset, 180) if h_offset > 0 else hsv[:,:,0]  # Hue is mod 180 -> Handle case when threshold goes out of bounds
            mask = cv2.inRange(np.dstack((hsv_offset, hsv[:,:,1:])), (self.H_min-h_offset, self.S_min, self.V_min), (np.mod(self.H_max-h_offset, 180), self.S_max, self.V_max))
            out = cv2.bitwise_and(img, img, mask=mask)

            # Print debugging info if enabled
            if self.show_pixel_info:
                cv2.circle(out, self.pixel, self.PIXEL_INFO_RADIUS, self.PIXEL_INFO_COLOR, self.PIXEL_INFO_THICKNESS)
                cv2.putText(out, "{} - {} ({})".format(self.pixel, pixel_hsv, self.get_str_lims()), (100, 100), cv2.FONT_HERSHEY_DUPLEX, 1, self.PIXEL_INFO_COLOR)
            cv2.imshow(self.WIN_NAME, out)

            # Render
            k = cv2.waitKey(1)
            if k == ord(' '):
                self.is_playing = not self.is_playing
            elif k>0:
                break

        cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Input: path to an image, a video, a webcam number or an IP camera")
    args = parser.parse_args()

    HSVthreshHelper(args.input).run()
