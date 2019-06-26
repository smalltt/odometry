import os
import json
import logging
import argparse
from tqdm import tqdm
from pathlib import Path

from . import __init_path__
import env

from odometry.utils.computation_utils import limit_resources
from odometry.preprocessing import parsers, estimators, prepare_trajectory


def str2bool(v):
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')


def initialize_estimators(target_size, optical_flow_checkpoint, depth_checkpoint=None):

    single_frame_estimators = list()

    quaternion2euler_estimator = estimators.Quaternion2EulerEstimator(input_col=['q_w', 'q_x', 'q_y', 'q_z'],
                                                                      output_col=['euler_x', 'euler_y', 'euler_z'])
    single_frame_estimators.append(quaternion2euler_estimator)

    if depth_checkpoint:
        struct2depth_estimator = estimators.Struct2DepthEstimator(input_col='path_to_rgb',
                                                                  output_col='path_to_depth',
                                                                  sub_dir='depth',
                                                                  checkpoint=depth_checkpoint,
                                                                  height=target_size[0],
                                                                  width=target_size[1])
        single_frame_estimators.append(struct2depth_estimator)

    cols = ['euler_x', 'euler_y', 'euler_z', 't_x', 't_y', 't_z']
    input_col = cols + [col + '_next' for col in cols]
    output_col = cols
    global2relative_estimator = estimators.Global2RelativeEstimator(input_col=input_col,
                                                                    output_col=output_col)

    pwcnet_estimator = estimators.PWCNetEstimator(input_col=['path_to_rgb', 'path_to_rgb_next'],
                                                  output_col='path_to_optical_flow',
                                                  sub_dir='optical_flow',
                                                  checkpoint=optical_flow_checkpoint)

    pair_frames_estimators = [global2relative_estimator, pwcnet_estimator]
    return single_frame_estimators, pair_frames_estimators


def initialize_parser(dataset_type):
    if dataset_type == 'kitti':
        return parsers.KITTIParser
    elif dataset_type == 'discoman':
        return parsers.DISCOMANJSONParser
    elif dataset_type == 'tum':
        return parsers.TUMParser
    elif dataset_type == 'retailbot':
        return parsers.RetailBotParser
    else:
        raise RuntimeError('Unexpected dataset type')


def get_all_trajectories(dataset_root):

    if not isinstance(dataset_root, Path):
        dataset_root = Path(dataset_root)

    logger = logging.getLogger('prepare_dataset')

    trajectories = list()
    for d in dataset_root.rglob('**/*'):
        if list(d.glob('*traj.json')) or \
                list(d.glob('rgb.txt')) or \
                list(d.glob('image_2')) or \
                list(d.glob('camera_gt.csv')):
            logger.info(f'Trajectory {d.as_posix()} added')
            trajectories.append(d.as_posix())

    return trajectories


def set_logger(output_dir):
    fh = logging.FileHandler(output_dir.joinpath('log.txt').as_posix(), mode='w+')
    fh.setLevel(logging.DEBUG)

    logger = logging.getLogger('prepare_dataset')
    logger.setLevel(logging.DEBUG)
    logger.addHandler(fh)


def prepare_dataset(dataset_type, dataset_root, output_dir, target_size, optical_flow_checkpoint,
                    depth_checkpoint=None):

    limit_resources()

    if not isinstance(output_dir, Path):
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    set_logger(output_dir)

    sf_estimators, pf_estimators = initialize_estimators(target_size,
                                                         optical_flow_checkpoint=optical_flow_checkpoint,
                                                         depth_checkpoint=depth_checkpoint)

    parser_class = initialize_parser(dataset_type)
    trajectories = get_all_trajectories(dataset_root)

    with open(output_dir.joinpath('config.json').as_posix(), mode='w+') as f:
        dataset_config = {'depth_checkpoint': depth_checkpoint, 'optical_flow_checkpoint': optical_flow_checkpoint}
        json.dump(dataset_config, f)

    for trajectory in tqdm(trajectories):
        trajectory_parser = parser_class(trajectory)
        trajectory_name = os.path.basename(trajectory)
        output_dir = output_dir.joinpath(trajectory_name)
        df = prepare_trajectory(output_dir.as_posix(),
                                parser=trajectory_parser,
                                single_frame_estimators=sf_estimators,
                                pair_frames_estimators=pf_estimators,
                                stride=1)
        df.to_csv(output_dir.joinpath('df.csv').as_posix(), index=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', type=str, choices=['kitti', 'discoman', 'tum', 'retailbox'])
    parser.add_argument('--dataset_root', type=str)
    parser.add_argument('--output_dir', type=str)
    parser.add_argument('--of_checkpoint', type=str,
                        default='/Vol0/user/f.konokhov/tfoptflow/tfoptflow/tmp/pwcnet.ckpt-84000')
    parser.add_argument('--depth', type=str2bool, default=True)
    parser.add_argument('--depth_checkpoint', type=str,
                        default=os.path.join(env.PROJECT_PATH, 'weights/model-199160'))
    parser.add_argument('--target_size', type=int, nargs='+')
    args = parser.parse_args()

    prepare_dataset(args.dataset,
                    dataset_root=args.dataset_root,
                    output_dir=args.output_dir,
                    target_size=args.target_size,
                    optical_flow_checkpoint=args.of_checkpoint,
                    depth_checkpoint=args.depth_checkpoint if args.depth else None)
