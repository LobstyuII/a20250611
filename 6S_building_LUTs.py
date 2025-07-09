# python 6S_building_LUTs.py --shard-id 0 --total-shards 20 # 0709 9000p
# python 6S_building_LUTs.py --shard-id 1 --total-shards 20 # 0709 gao
# python 6S_building_LUTs.py --shard-id 2 --total-shards 20
# python 6S_building_LUTs.py --shard-id 3 --total-shards 20

import os
import time
import netCDF4 as nc
import numpy as np
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from Py6S import *
import multiprocessing
import argparse

# 配置参数
PATHS = {
    "lut_cache": "D:/H8_data/LUT_Cache/"
}
os.makedirs(PATHS["lut_cache"], exist_ok=True)

# 基于2016年分析结果优化的参数边界
OPTIMIZED_PARAMS = {
    'solar_zenith': (13.12, 83.30),  # 太阳天顶角 (度)
    'view_zenith': (38.99, 58.86),  # 观测天顶角 (度)
    'relative_azimuth': (3.82, 165.01),  # 相对方位角 (度)
    'aot550': (0.0511, 1.4357),  # AOD 550nm
    'water': (0.1974, 6.5669),  # 水汽含量 (g/cm²)
    'ozone': (0.2354, 0.4020),  # 臭氧含量 (cm-atm)
    'toa_reflectance': (0.0, 1.0)  # TOA反射率
}

LUT_PARAMS = {
    'solar_zenith': np.linspace(OPTIMIZED_PARAMS['solar_zenith'][0],
                                OPTIMIZED_PARAMS['solar_zenith'][1], 12),
    'view_zenith': np.linspace(OPTIMIZED_PARAMS['view_zenith'][0],
                               OPTIMIZED_PARAMS['view_zenith'][1], 10),
    'relative_azimuth': np.linspace(OPTIMIZED_PARAMS['relative_azimuth'][0],
                                    OPTIMIZED_PARAMS['relative_azimuth'][1], 12),
    'aot550': np.array([
        OPTIMIZED_PARAMS['aot550'][0],
        0.1,
        0.3,
        0.7,
        OPTIMIZED_PARAMS['aot550'][1]
    ]),
    'water': np.array([
        OPTIMIZED_PARAMS['water'][0],
        0.5,
        1.0,
        3.0,
        OPTIMIZED_PARAMS['water'][1]
    ]),
    'ozone': np.array([
        OPTIMIZED_PARAMS['ozone'][0],
        (OPTIMIZED_PARAMS['ozone'][0] + OPTIMIZED_PARAMS['ozone'][1])/2,
        OPTIMIZED_PARAMS['ozone'][1]
    ]),
    'toa_reflectance': np.linspace(OPTIMIZED_PARAMS['toa_reflectance'][0],
                                   OPTIMIZED_PARAMS['toa_reflectance'][1], 10),
    'bands': [0.64, 0.86]
}

# BRDF参数映射
LUCC_TO_BRDF = {
    1: {"model": "Rahman", "intensity": 0.3, "asymmetry": 0.1, "structural": 0.5},
    2: {"model": "Rahman", "intensity": 0.35, "asymmetry": 0.12, "structural": 0.55},
    3: {"model": "Rahman", "intensity": 0.25, "asymmetry": 0.08, "structural": 0.45},
    4: {"model": "Rahman", "intensity": 0.3, "asymmetry": 0.1, "structural": 0.5},
    5: {"model": "Rahman", "intensity": 0.2, "asymmetry": 0.05, "structural": 0.4},
    6: {"model": "Rahman", "intensity": 0.4, "asymmetry": 0.15, "structural": 0.6},
    7: {"model": "Rahman", "intensity": 0.35, "asymmetry": 0.12, "structural": 0.55},
    8: {"model": "Walthall", "param1": 0.5, "param2": 0.2, "param3": 0.1, "albedo": 0.25},
    9: {"model": "Walthall", "param1": 0.4, "param2": 0.15, "param3": 0.05, "albedo": 0.3},
    10: {"model": "Lambertian", "albedo": 0.35},
    11: {"model": "Lambertian", "albedo": 0.1},
    12: {"model": "Lambertian", "albedo": 0.4},
    13: {"model": "Walthall", "param1": 0.6, "param2": 0.25, "param3": 0.15, "albedo": 0.35},
    14: {"model": "Lambertian", "albedo": 0.7},
    15: {"model": "Lambertian", "albedo": 0.05},
    16: {"model": "Lambertian", "albedo": 0.02},
    17: {"model": "Lambertian", "albedo": 0.02},
    255: {"model": "Lambertian", "albedo": 0.2}
}

# 大气廓线映射
LATITUDE_TO_PROFILE = {
    (-90, -30): {5: AtmosProfile.SubarcticWinter, 9: AtmosProfile.SubarcticSummer},
    (-30, 30): AtmosProfile.Tropical,
    (30, 60): {5: AtmosProfile.MidlatitudeWinter, 9: AtmosProfile.MidlatitudeSummer},
    (60, 90): {5: AtmosProfile.SubarcticWinter, 9: AtmosProfile.SubarcticSummer}
}


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def generate_lut_key(profile_type, brdf_params):
    """生成LUT的唯一标识键"""
    profile_str = str(profile_type).split('.')[-1]
    brdf_str = "_".join([f"{k}={v}" for k, v in sorted(brdf_params.items())])
    return f"{profile_str}_{brdf_str}"


def create_lut(profile_type, brdf_params):
    """创建查找表(LUT)"""
    lut_key = generate_lut_key(profile_type, brdf_params)
    lut_file = os.path.join(PATHS["lut_cache"], f"{lut_key}.nc")

    if os.path.exists(lut_file):
        print(f"[{timestamp()}] [LUT] 使用缓存: {lut_key}")
        with nc.Dataset(lut_file) as ds:
            return lut_key, ds['sr'][:]

    print(f"[{timestamp()}] [LUT] 生成LUT: {lut_key}")
    s = SixS()
    s.altitudes.set_sensor_custom_altitude(99)
    s.aero_profile = AeroProfile.PredefinedType(AeroProfile.Continental)
    s.atmos_profile = profile_type

    # 设置BRDF模型
    model = brdf_params["model"]
    if model == "Rahman":
        s.ground_reflectance = GroundReflectance.HomogeneousRahman(
            brdf_params["intensity"], brdf_params["asymmetry"], brdf_params["structural"])
    elif model == "Walthall":
        s.ground_reflectance = GroundReflectance.HomogeneousWalthall(
            brdf_params["param1"], brdf_params["param2"], brdf_params["param3"], brdf_params["albedo"])
    else:  # Lambertian
        s.ground_reflectance = GroundReflectance.HomogeneousLambertian(brdf_params["albedo"])

    # 创建LUT数组
    lut_shape = tuple(len(LUT_PARAMS[k]) for k in [
        'solar_zenith', 'view_zenith', 'relative_azimuth',
        'aot550', 'water', 'ozone', 'toa_reflectance'
    ]) + (len(LUT_PARAMS['bands']),)

    lut_data = np.zeros(lut_shape, dtype=np.float32)
    total_points = np.prod(lut_shape[:-1])
    processed = 0
    start_time = time.time()

    # 创建参数网格
    grid = np.array(np.meshgrid(
        LUT_PARAMS['solar_zenith'],
        LUT_PARAMS['view_zenith'],
        LUT_PARAMS['relative_azimuth'],
        LUT_PARAMS['aot550'],
        LUT_PARAMS['water'],
        LUT_PARAMS['ozone'],
        LUT_PARAMS['toa_reflectance'],
        indexing='ij'
    )).T.reshape(-1, 7)

    # 批量处理
    for i, params in enumerate(grid):
        sz, vz, az, aot, water, ozone, toa = params

        s.geometry = Geometry.User()
        s.geometry.solar_z = sz
        s.geometry.view_z = vz
        s.geometry.relative_azimuth = az
        s.aot550 = aot
        s.atmos_profile = AtmosProfile.UserWaterAndOzone(water, ozone)
        s.atmos_corr = AtmosCorr.AtmosCorrBRDFFromReflectance(toa)

        band_results = []
        for band in LUT_PARAMS['bands']:
            s.wavelength = Wavelength(band)
            try:
                s.run()
                band_results.append(s.outputs.pixel_reflectance)
            except:
                band_results.append(np.nan)

        # 计算索引位置
        idx = tuple(
            np.where(LUT_PARAMS[dim] == val)[0][0]
            for dim, val in zip([
                'solar_zenith', 'view_zenith', 'relative_azimuth',
                'aot550', 'water', 'ozone', 'toa_reflectance'
            ], params)
        )

        for band_idx, result in enumerate(band_results):
            lut_data[idx + (band_idx,)] = result

        # 进度更新
        processed += 1
        if processed % 100 == 0 or processed == total_points:
            elapsed = time.time() - start_time
            remaining = (total_points - processed) * (elapsed / processed) if processed > 0 else 0
            print(f"[{timestamp()}] [LUT] 进度: {processed}/{total_points} "
                  f"({processed / total_points * 100:.1f}%) - 剩余: {remaining:.0f}s")

    # 保存LUT
    ds = nc.Dataset(lut_file, 'w')
    for dim_name, values in LUT_PARAMS.items():
        if dim_name == 'bands':
            continue
        dim = ds.createDimension(dim_name, len(values))
        var = ds.createVariable(dim_name, 'f4', (dim_name,))
        var[:] = values

    band_dim = ds.createDimension('band', len(LUT_PARAMS['bands']))
    band_var = ds.createVariable('band', 'f4', ('band',))
    band_var[:] = LUT_PARAMS['bands']

    sr_var = ds.createVariable('sr', 'f4', tuple(LUT_PARAMS.keys())[:-1] + ('band',))
    sr_var[:] = lut_data
    ds.close()

    print(f"[{timestamp()}] [LUT] LUT已保存: {lut_file}")
    return lut_key, lut_data


def get_brdf_params(lucc_value):
    """获取BRDF参数"""
    lucc_int = int(lucc_value)
    return LUCC_TO_BRDF.get(lucc_int, LUCC_TO_BRDF[255])


def get_unique_profiles():
    """获取所有大气廓线类型"""
    unique_profiles = set()
    for profile_dict in LATITUDE_TO_PROFILE.values():
        if isinstance(profile_dict, dict):
            unique_profiles.update(profile_dict.values())
        else:
            unique_profiles.add(profile_dict)
    return unique_profiles


def print_optimized_params():
    """打印优化后的参数范围"""
    print("\n优化后的LUT参数范围:")
    print("=" * 70)
    print("{:<20} {:<15} {:<15} {:<10} {:<10}".format(
        "参数", "最小值", "最大值", "点数", "单位"))
    print("-" * 70)

    # 更新点数信息以匹配新的LUT网格
    params_info = [
        ("solar_zenith", "度", len(LUT_PARAMS['solar_zenith'])),  # 12点
        ("view_zenith", "度", len(LUT_PARAMS['view_zenith'])),     # 10点
        ("relative_azimuth", "度", len(LUT_PARAMS['relative_azimuth'])),  # 12点
        ("aot550", "无单位", len(LUT_PARAMS['aot550'])),           # 5点
        ("water", "g/cm²", len(LUT_PARAMS['water'])),             # 5点
        ("ozone", "cm-atm", len(LUT_PARAMS['ozone'])),            # 3点
        ("toa_reflectance", "无单位", len(LUT_PARAMS['toa_reflectance']))  # 11点
    ]

    for param, unit, points in params_info:
        values = LUT_PARAMS[param]
        print("{:<20} {:<15.4f} {:<15.4f} {:<10} {:<10}".format(
            param, min(values), max(values), points, unit))

    print("=" * 70)
    print(f"波段: {LUT_PARAMS['bands']} (μm)")
    print("=" * 70)


def main():
    # 新增：命令行参数解析
    parser = argparse.ArgumentParser(description='生成LUT分片')
    parser.add_argument('--shard-id', type=int, default=0,
                        help='当前分片的ID (0到total-shards-1)')
    parser.add_argument('--total-shards', type=int, default=1,
                        help='总分片数')
    args = parser.parse_args()

    print(f"[{timestamp()}] 开始生成LUTs (分片 {args.shard_id}/{args.total_shards})")
    print_optimized_params()

    # 获取所有可能的BRDF和大气廓线组合
    tasks = []
    unique_profiles = get_unique_profiles()

    for lucc_value in set(LUCC_TO_BRDF.keys()):
        brdf_params = get_brdf_params(lucc_value)
        for profile in unique_profiles:
            tasks.append((profile, brdf_params))

    # 新增：任务分片逻辑
    total_tasks = len(tasks)
    shard_size = total_tasks // args.total_shards
    start_idx = args.shard_id * shard_size
    end_idx = start_idx + shard_size

    # 处理最后一个分片的剩余任务
    if args.shard_id == args.total_shards - 1:
        end_idx = total_tasks

    tasks = tasks[start_idx:end_idx]
    print(f"[{timestamp()}] 当前分片任务数量: {len(tasks)}/{total_tasks}")

    # 并行生成LUT
    completed = 0
    with ProcessPoolExecutor(max_workers=multiprocessing.cpu_count()) as executor:
        futures = {executor.submit(create_lut, *task): task for task in tasks}

        for future in as_completed(futures):
            try:
                lut_key, _ = future.result()
                completed += 1
                print(f"[{timestamp()}] [{completed}/{len(tasks)}] LUT完成: {lut_key}")
            except Exception as e:
                print(f"[{timestamp()}] [ERROR] LUT生成失败: {str(e)}")

    print(f"[{timestamp()}] 分片 {args.shard_id}/{args.total_shards} 完成")


if __name__ == "__main__":
    main()