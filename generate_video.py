import matplotlib
matplotlib.use('Agg')

from preprocess_experiments import HDF5_WEIGHT_GROUP_NAME
from aux_tools import format_axis_as_timedelta, _min, _max, str2bool, list_subfolders, DEFAULT_TIMEZONE, date_range, time_to_float, str_to_datetime, plt_fig_to_cv2_img
import cv2
import numpy as np
from scipy.interpolate import interp1d
from matplotlib import pyplot as plt
from datetime import datetime, timedelta
import os
import h5py
import argparse


def generate_multicam_video(experiment_base_folder, video_out_filename=None, t_start=0, t_end=-1, video_fps=25, visualize=False, overwrite=False):
    t_experiment_start = experiment_base_folder.rsplit('/', 1)[-1]  # Last folder in the path should indicate time at which experiment started
    if video_out_filename is None:
        video_out_filename = os.path.join(experiment_base_folder, "multicam_{}.mp4".format(t_experiment_start))
    if os.path.exists(video_out_filename):
        print("Video {} already exists, {}".format(video_out_filename, "overwriting..." if overwrite else "nothing to do!"))
        if not overwrite:  # Exit if don't want to overwrite
            return video_out_filename
    else:
        print("Generating multi-cam video '{}'".format(video_out_filename))

    # Load videos and get their frame timestamps
    videos_in = []
    camera_timestamps = []
    t_latest_start = datetime.min.replace(tzinfo=DEFAULT_TIMEZONE)
    t_earliest_end = datetime.max.replace(tzinfo=DEFAULT_TIMEZONE)
    for cam in (range(4)):
        camera_filename = os.path.join(experiment_base_folder, "cam{}_{}".format(cam+1, t_experiment_start))
        videos_in.append(cv2.VideoCapture(camera_filename + ".mp4"))
        camera_info = h5py.File(camera_filename + ".h5", 'r')
        camera_timestamps.append(np.array([str_to_datetime(t) for t in camera_info.get("t_str")]))
        t_latest_start = _max(camera_timestamps[-1][0], t_latest_start)
        t_earliest_end = _min(camera_timestamps[-1][-1], t_earliest_end)

    # Interpolate time (nearest frame) as if cameras had been sampled at constant fps
    t_cam = np.array(list(date_range(t_latest_start, t_earliest_end, timedelta(seconds=1.0/video_fps))))
    to_float = lambda t_arr: np.array(time_to_float(t_arr, t_latest_start))
    frame_nums = []
    for t in camera_timestamps:
        frame_nums.append(interp1d(to_float(t), range(len(t)), kind='nearest', copy=False, assume_sorted=True)(to_float(t_cam)).astype(np.uint16))
    frame_nums = np.array(frame_nums)

    # Set up video file
    video_size = (int(videos_in[0].get(cv2.CAP_PROP_FRAME_WIDTH)), int(videos_in[0].get(cv2.CAP_PROP_FRAME_HEIGHT)))
    video_out = cv2.VideoWriter(video_out_filename, cv2.VideoWriter_fourcc(*'avc1'), video_fps, video_size)
    rgb_data = np.zeros((2*video_size[1], 2*video_size[0], 3), dtype=np.uint8)
    img = np.zeros((video_size[1], video_size[0], 3), dtype=np.uint8)

    # Save timing params so t_cam can be reconstructed (and the weights can be aligned)
    with h5py.File(os.path.splitext(video_out_filename)[0] + ".h5", 'w') as f_hdf5:
        f_hdf5.attrs['t_start'] = str(t_cam[0]).encode('utf8')
        f_hdf5.attrs['t_end'] = str(t_cam[-1]).encode('utf8')
        f_hdf5.attrs['fps'] = video_fps
        f_hdf5.create_dataset('frame_nums', data=frame_nums)

    # Generate video
    for n,t in enumerate(t_cam):
        curr_t = (t-t_cam[0]).total_seconds()
        if curr_t < t_start or (t_end > 0 and curr_t > t_end): continue

        for i in range(len(frame_nums)):
            videos_in[i].set(cv2.CAP_PROP_POS_FRAMES, frame_nums[i,n])
            ok = videos_in[i].read(img)
            assert ok, "Couldn't read frame {} from camera {}!".format(n, i+1)
            if i == 0:
                rgb_data[:img.shape[0], :img.shape[1], :] = img
            elif i == 1:
                rgb_data[img.shape[0]:, :img.shape[1], :] = img
            elif i == 2:
                rgb_data[:img.shape[0], img.shape[1]:, :] = img
            elif i == 3:
                rgb_data[img.shape[0]:, img.shape[1]:, :] = img

        # Output the image (show it and write to file)
        cv2.resize(rgb_data, None, img, fx=0.5, fy=0.5)
        video_out.write(img)
        print("{} out of {} frames ({:6.2f}%) written! ({})".format(n+1, len(t_cam), 100.0*(n+1)/len(t_cam), video_out_filename))

        if visualize:
            cv2.imshow("Frame", img)
            # Let the visualization be stopped by pressing a key
            k = cv2.waitKey(1)
            if k > 0:
                print('Key pressed, exiting!')
                break

    # Close video file
    video_out.release()  # Make sure to release the video so it's actually written to disk
    print("Video successfully saved as '{}'! :)".format(video_out_filename))
    return video_out_filename


def generate_video(experiment_base_folder, camera_id=3, weight_id=5309446, t_lims=3, t_start=0, t_end=-1, weight_plot_scale=0.3, video_fps=25, visualize=True, save_video=False, cb_event_start_or_end=None, out_scale=0.5):
    multiple_cams = (camera_id < 0)
    if multiple_cams:
        weight_plot_scale = 1.0  # Overwrite setting, weight plots will be hstacked (same height)
        video_in_filename = generate_multicam_video(experiment_base_folder, t_start=t_start, t_end=t_end, video_fps=video_fps)
        video_in = cv2.VideoCapture(video_in_filename)
        with h5py.File(os.path.splitext(video_in_filename)[0] + ".h5", 'r') as h5_cam:
            t_cam = np.array(list(date_range(str_to_datetime(h5_cam.attrs['t_start']), str_to_datetime(h5_cam.attrs['t_end']), timedelta(seconds=1.0/h5_cam.attrs['fps']))))
    else:
        t_experiment_start = experiment_base_folder.rsplit('/', 1)[-1]  # Last folder in the path should indicate time at which experiment started
        camera_filename = os.path.join(experiment_base_folder, "cam{}_{}".format(camera_id, t_experiment_start))
        video_in = cv2.VideoCapture(camera_filename + ".mp4")
        camera_info = h5py.File(camera_filename + ".h5", 'r')
        t_cam = np.array([str_to_datetime(t) for t in camera_info.get("t_str")])
    video_in_width = int(video_in.get(cv2.CAP_PROP_FRAME_WIDTH))
    video_in_height = int(video_in.get(cv2.CAP_PROP_FRAME_HEIGHT))
    rgb_data = np.zeros((video_in_height, video_in_width, 3), dtype=np.uint8)

    # Read all weight sensors for the full experiment duration at once
    t_experiment_start = experiment_base_folder.rsplit('/', 1)[-1]  # Last folder in the path should indicate time at which experiment started
    with h5py.File(os.path.join(experiment_base_folder, "weights_{}.h5".format(t_experiment_start)), 'r') as h5_weights:
        multiple_weights = (weight_id < 0)
        if multiple_weights:
            weight_t = np.array([str_to_datetime(t) for t in h5_weights['t_str']])
            weight_data = h5_weights['w'][:]
            w = np.sum(weight_data, axis=1)
        else:
            plate_info = h5_weights[HDF5_WEIGHT_GROUP_NAME.format(weight_id)]
            weight_t = np.array([str_to_datetime(t) for t in plate_info['t_str']])
            weight_data = plate_info['w'][:]
            w = [weight_data]
    t_w = time_to_float(weight_t, weight_t[0])

    # Manually align weight and cam timestamps (not synced for some reason)
    weight_to_cam_t_offset = weight_t[0] + timedelta(seconds=13)  # camera_timestamps[0]

    # Set up matplotlib figure
    fig = plt.figure(figsize=(3.5,5) if multiple_cams else (4,2))
    num_axes = len(weight_data) if multiple_weights else 1
    ax = fig.subplots(num_axes, 1, sharex=True, squeeze=False)
    curr_t_lines = []
    for i in range(num_axes):
        shelf_i = num_axes - (i+1)  # Shelf 1 is at the bottom
        ax[i,0].plot(t_w, w[shelf_i])
        ax[i,0].set_title('Shelf {}'.format(shelf_i+1) if multiple_weights else 'Load cell #{}'.format(weight_id))
        ax[i,0].set_ylabel('Weight (g)')
        format_axis_as_timedelta(ax[i,0].xaxis)
        curr_t_lines.append(ax[i,0].axvline(0, linestyle='--', color='black', linewidth=1))
    # Render the figure once to get its dimensions
    fig.canvas.draw()
    weight_img = plt_fig_to_cv2_img(fig)
    weight_scale = weight_plot_scale*rgb_data.shape[0]/weight_img.shape[0]
    weight_fig_dimensions = (weight_scale*np.array(weight_img.shape[:2])).astype(int)
    # Allocate extra space when the figure is going to be plotted to the right of the video
    if weight_plot_scale == 1:  # Render the figure once to get its dimensions
        rgb_data = np.zeros((rgb_data.shape[0], rgb_data.shape[1]+weight_fig_dimensions[1], 3), dtype=np.uint8)

    # Set up video file
    if save_video:
        video_filename = 'AIM3S_experiment.mp4'
        video_out = cv2.VideoWriter(video_filename, cv2.VideoWriter_fourcc(*'avc1'), video_fps, (video_in_width, video_in_height))

    TIME_INCREMENT = timedelta(seconds=0.1)  # How much to shift the time offset cameras-weights from keyboard input (ASDW)
    FRAME_INCREMENT = 8  # How many frames to skip forward/backward on keyboard input (arrow keys)
    LEFT_RIGHT_MULTIPLIER = 10  # How much larger the skip is when using left-right (A-D) vs up-down (or W-S)
    n = -1  # Frame number
    is_paused = False
    refresh_weight = True
    do_skip_frames = False
    while n < len(t_cam)-1:
        if not is_paused or do_skip_frames:
            n += 1
            ok = video_in.read(rgb_data[:,:video_in_width,:])
            assert ok, "Couldn't read frame {}!".format(n)
            print("Read frame {} out of {} frames ({:6.2f}%)".format(n+1, len(t_cam), 100.0*(n+1)/len(t_cam)))

        if refresh_weight:
            # Update current time
            curr_t = (t_cam[n]-weight_to_cam_t_offset).total_seconds()
            if (t_start > 0 and curr_t < t_start) or (t_end > 0 and curr_t > t_end): continue
            ax[-1,0].set_xlim(curr_t-t_lims, curr_t+t_lims)

            # Update weight plot and convert to image
            for l in curr_t_lines: l.set_xdata(curr_t)
            fig.canvas.draw()
            weight_img = plt_fig_to_cv2_img(fig)

            # Rescale weight (make the plot occupy weight_plot_scale of the whole camera frame)
            if weight_plot_scale == 1:  # Place the weight plot to the right of the camera frames
                cv2.resize(weight_img, None, rgb_data[:,video_in_width:,:], fx=weight_scale, fy=weight_scale)
            else:  # Overwrite bottom-right corner of RGB frame with weight plot
                cv2.resize(weight_img, None, rgb_data[-weight_fig_dimensions[0]:, -weight_fig_dimensions[1]:, :], fx=weight_scale, fy=weight_scale)

        # Output the image (show it and write to file)
        if save_video:
            video_out.write(rgb_data if out_scale==1 else cv2.resize(rgb_data, None, fx=out_scale, fy=out_scale))
            print("{} out of {} frames ({:6.2f}%) written!".format(n+1, len(t_cam), 100.0*(n+1)/len(t_cam)))

        if visualize:
            if not is_paused or refresh_weight:
                cv2.imshow("Frame", rgb_data if out_scale==1 else cv2.resize(rgb_data, None, fx=out_scale, fy=out_scale))
            # Let the visualization be stopped by pressing a key
            k = cv2.waitKeyEx(1 if not is_paused else 0)
            do_skip_frames = False
            refresh_weight = False
            if k == 63234:  # Left arrow (at least on my Mac)
                n -= LEFT_RIGHT_MULTIPLIER*FRAME_INCREMENT
                do_skip_frames = True
                refresh_weight = True
            elif k == 63235:  # Right arrow
                n += LEFT_RIGHT_MULTIPLIER*FRAME_INCREMENT
                do_skip_frames = True
                refresh_weight = True
            elif k == 63232:  # Up arrow
                n += FRAME_INCREMENT
                do_skip_frames = True
                refresh_weight = True
            elif k == 63233:  # Down arrow
                n -= FRAME_INCREMENT
                do_skip_frames = True
                refresh_weight = True
            elif k == ord('a'):
                weight_to_cam_t_offset -= LEFT_RIGHT_MULTIPLIER*TIME_INCREMENT
                refresh_weight = True
            elif k == ord('d'):
                weight_to_cam_t_offset += LEFT_RIGHT_MULTIPLIER*TIME_INCREMENT
                refresh_weight = True
            elif k == ord('w'):
                weight_to_cam_t_offset -= TIME_INCREMENT
                refresh_weight = True
            elif k == ord('s'):
                weight_to_cam_t_offset += TIME_INCREMENT
                refresh_weight = True
            elif k == ord('b') and cb_event_start_or_end is not None:
                cb_event_start_or_end(True, t_cam[n])
            elif k == ord('n') and cb_event_start_or_end is not None:
                cb_event_start_or_end(False, t_cam[n])
            elif k == ord(' '):
                is_paused = not is_paused
            elif k == 27 or (k > 0 and cb_event_start_or_end is None):  # Don't exit on unrecognized keys if labeling ground truth
                print('Key pressed, exiting!')
                cv2.destroyWindow("Frame")
                cv2.waitKey(1)
                break
            refresh_weight = refresh_weight or not is_paused

            if do_skip_frames:
                video_in.set(cv2.CAP_PROP_POS_FRAMES, n)
                n = int(video_in.get(cv2.CAP_PROP_POS_FRAMES))  # Don't let it go over the length of the video

    # Close video file
    if save_video:
        video_out.release()  # Make sure to release the video so it's actually written to disk
        print("Video successfully saved as '{}'! :)".format(video_filename))

    return weight_to_cam_t_offset, (weight_t[0]-weight_to_cam_t_offset).total_seconds()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", default="Dataset/Evaluation", help="Folder containing the experiment to visualize")
    parser.add_argument('-c', "--cam", default=-1, type=int, help="ID of the camera to visualize")
    parser.add_argument('-w', "--weight", default=-1, type=int, help="ID of the weight sensor to visualize")
    parser.add_argument('-l', "--t-lims", default=4, type=float, help="Length (in s) of the weight plot sliding window")
    parser.add_argument('-s', "--t-start", default=0, type=float, help="Experiment time at which to start generating the video")
    parser.add_argument('-e', "--t-end", default=-1, type=float, help="Experiment time at which to stop generating the video (-1 for no limit)")
    parser.add_argument('-k', "--scale", default=0.3, type=float, help="Ratio (0-1) to scale down the weight plot wrt the video's dimensions")
    parser.add_argument('-r', "--fps", default=25, type=int, help="Output video frame rate")
    parser.add_argument("--multi-cam", default=False, action="store_true", help="Add this flag to generate multi-cam videos")
    args = parser.parse_args()

    if args.multi_cam:
        from multiprocessing import Pool, cpu_count
        pool = Pool(processes=cpu_count() if True else 4)
        tasks_state = []

        folder_names = list_subfolders(args.folder, True)
        for experiment_folder in folder_names:
            task_state = pool.apply_async(generate_multicam_video, (os.path.join(args.folder, experiment_folder),), {'video_fps': args.fps, 'overwrite': False})
            tasks_state.append(task_state)

        for i,task_state in enumerate(tasks_state):
            task_state.wait()
            if not task_state.successful():
                print("Uh oh... Task {}: {}".format(i+1, task_state._value))
    else:
        generate_video(args.folder, args.cam, args.weight, args.t_lims, args.t_start, args.t_end, args.scale, args.fps, visualize=False, save_video=True, out_scale=1)
