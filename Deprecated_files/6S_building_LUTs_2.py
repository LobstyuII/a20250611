# python 6S_building_LUTs_2.py --shard-id 0 --total-shards 3 # 0709 7000p
# python 6S_building_LUTs_2.py --shard-id 1 --total-shards 3 # 0709 9000p
# python 6S_building_LUTs_2.py --shard-id 2 --total-shards 3



import os
import time
import netCDF4 as nc
import numpy as np
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from Py6S import *
import multiprocessing
import argparse
from multiprocessing import shared_memory
import json

# 配置参数
PATHS = {
    "lut_cache": "D:/H8_data/LUT_Cache/",
    "parameter_stats": "D:/H8_Data/Parameter_Analysis/parameter_statistics.json"  # 参数统计文件路径
}
os.makedirs(PATHS["lut_cache"], exist_ok=True)

# 全局初始化标志
LUT_PARAMS_INITIALIZED = False

# 从JSON文件加载参数统计
def load_parameter_statistics():
    """从JSON文件加载参数统计结果"""
    try:
        with open(PATHS["parameter_stats"], 'r') as f:
            stats = json.load(f)
            print(f"[{timestamp()}] 成功加载参数统计")
            return stats
    except Exception as e:
        print(f"[{timestamp()}] [ERROR] 加载参数统计失败: {str(e)}")
        return None


# 基于参数统计设置优化参数
def setup_optimized_params(stats):
    """基于统计结果设置优化参数"""
    optimized_params = {}
    lucc_categories = []

    if stats:
        # 设置连续参数的范围
        for param in ['solar_zenith', 'view_zenith', 'relative_azimuth',
                      'aot550', 'water', 'ozone']:
            if param in stats:
                optimized_params[param] = (
                    stats[param]['recommended_min'],
                    stats[param]['recommended_max']
                )

        # 设置TOA反射率范围 (开区间)
        for band in ['toa_reflectance_band03', 'toa_reflectance_band04']:
            if band in stats:
                min_val = max(0.001, stats[band]['recommended_min'])  # 最小0.001
                max_val = min(0.999, stats[band]['recommended_max'])  # 最大0.999
                optimized_params[band] = (min_val, max_val)

        # 设置LUCC类别 - 添加频率过滤
        if 'lucc' in stats:
            lucc_stats = stats['lucc']
            categories = lucc_stats['categories']
            frequencies = lucc_stats['frequencies']

            # 过滤频率低于2.5%的类别
            filtered_categories = []
            for cat, freq in zip(categories, frequencies):
                if freq >= 0.025:  # 2.5%阈值
                    filtered_categories.append(cat)

            lucc_categories = sorted(filtered_categories)
            print(f"[{timestamp()}] 过滤后LUCC类别: {lucc_categories} (原始类别数: {len(categories)})")

            # 移除无效类别
            valid_categories = set(LUCC_TO_BRDF.keys())
            lucc_categories = [c for c in lucc_categories if c in valid_categories]
        else:
            print(f"[{timestamp()}] [WARN] 统计中缺少LUCC数据")

    # 设置默认值（如果统计不可用）
    defaults = {
        'solar_zenith': (0, 85),
        'view_zenith': (0, 60),
        'relative_azimuth': (0, 180),
        'aot550': (0.01, 3.0),
        'water': (0.1, 5.0),
        'ozone': (0.1, 0.5),
        'toa_reflectance_band03': (0.01, 0.99),
        'toa_reflectance_band04': (0.01, 0.99)
    }

    for param, default in defaults.items():
        if param not in optimized_params:
            optimized_params[param] = default
            print(f"[{timestamp()}] [WARN] 使用默认参数: {param}={default}")

    # 如果没有有效的LUCC类别，使用所有定义的类别
    if not lucc_categories:
        lucc_categories = sorted(LUCC_TO_BRDF.keys())
        # 移除无效类别
        valid_categories = set(LUCC_TO_BRDF.keys())
        lucc_categories = [c for c in lucc_categories if c in valid_categories]
        print(f"[{timestamp()}] [WARN] 使用全量LUCC类别: {lucc_categories}")

    return optimized_params, lucc_categories


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

# 全局变量，将在main中初始化
OPTIMIZED_PARAMS = None
LUCC_CATEGORIES = None
LUT_PARAMS = {}


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def generate_lut_key(profile_type, lucc_value):
    """生成LUT的唯一标识键"""
    profile_str = str(profile_type).split('.')[-1]
    return f"{profile_str}_LUCC{lucc_value}"


def init_worker(shared_mem_name, lut_shape, bands):
    """初始化工作进程"""
    global shared_array, worker_bands
    worker_bands = bands

    # 连接到共享内存
    try:
        existing_shm = shared_memory.SharedMemory(name=shared_mem_name)
        # 创建与共享内存关联的数组
        shared_array = np.ndarray(lut_shape, dtype=np.float32, buffer=existing_shm.buf)
    except Exception as e:
        print(f"[{timestamp()}] [ERROR] 工作进程初始化失败: {str(e)}")
        raise


def calculate_point(params, lucc_value, profile_type, fixed_aot, fixed_ozone):
    """计算单个参数点 - 使用固定的AOT和臭氧值"""
    # 现在params中只包含：sz, vz, az, water, toa, idx_tuple
    sz, vz, az, water, toa, idx_tuple = params
    idx = tuple(int(i) for i in idx_tuple)  # 转换为整数元组

    try:
        # 创建独立的6S实例
        s = SixS()
        s.altitudes.set_sensor_custom_altitude(99)
        s.aero_profile = AeroProfile.PredefinedType(AeroProfile.Continental)
        s.atmos_profile = profile_type

        # 设置BRDF模型 (基于LUCC值)
        brdf_params = LUCC_TO_BRDF.get(lucc_value, LUCC_TO_BRDF[255])
        model = brdf_params["model"]
        if model == "Rahman":
            s.ground_reflectance = GroundReflectance.HomogeneousRahman(
                brdf_params["intensity"], brdf_params["asymmetry"], brdf_params["structural"])
        elif model == "Walthall":
            s.ground_reflectance = GroundReflectance.HomogeneousWalthall(
                brdf_params["param1"], brdf_params["param2"], brdf_params["param3"], brdf_params["albedo"])
        else:  # Lambertian
            s.ground_reflectance = GroundReflectance.HomogeneousLambertian(brdf_params["albedo"])

        # 设置几何和大气参数
        s.geometry = Geometry.User()
        s.geometry.solar_z = sz
        s.geometry.view_z = vz
        s.geometry.relative_azimuth = az

        # 使用固定值替代原网格值
        s.aot550 = fixed_aot
        s.atmos_profile = AtmosProfile.UserWaterAndOzone(water, fixed_ozone)
        s.atmos_corr = AtmosCorr.AtmosCorrBRDFFromReflectance(toa)

        # 计算所有波段
        results = []
        for band in worker_bands:
            s.wavelength = Wavelength(band)
            s.run()
            results.append(s.outputs.pixel_reflectance)

        # 直接写入共享内存
        for band_idx, result in enumerate(results):
            shared_array[idx + (band_idx,)] = result

    except Exception as e:
        print(f"[{timestamp()}] [ERROR] 计算点失败: {str(e)}")
        # 标记为NaN
        for band_idx in range(len(worker_bands)):
            shared_array[idx + (band_idx,)] = np.nan


def create_lut(profile_type, lucc_value, aot_value, ozone_value):
    """创建查找表(LUT) - 针对固定AOT550和臭氧值"""
    # 生成LUT键名时包含固定参数
    lut_key = f"{generate_lut_key(profile_type, lucc_value)}_AOT{aot_value}_OZ{ozone_value}"
    lut_file = os.path.join(PATHS["lut_cache"], f"{lut_key}.nc")

    if os.path.exists(lut_file):
        print(f"[{timestamp()}] [LUT] 使用缓存: {lut_key}")
        with nc.Dataset(lut_file) as ds:
            return lut_key, ds['sr'][:]

    print(f"[{timestamp()}] [LUT] 生成LUT切片: {lut_key}")

    # 新LUT形状（移除了aot550和ozone）
    lut_shape = tuple(len(LUT_PARAMS[k]) for k in [
        'solar_zenith', 'view_zenith', 'relative_azimuth', 'water', 'toa_reflectance'
    ]) + (len(LUT_PARAMS['bands']),)

    # 计算总内存大小
    total_size = int(np.prod(lut_shape) * np.dtype(np.float32).itemsize)

    # 创建共享内存
    shm = shared_memory.SharedMemory(create=True, size=total_size)
    shared_array = np.ndarray(lut_shape, dtype=np.float32, buffer=shm.buf)
    shared_array[:] = np.nan  # 初始化为NaN

    # 创建参数网格（仅变化维度）
    param_names = ['solar_zenith', 'view_zenith', 'relative_azimuth', 'water', 'toa_reflectance']
    mesh = np.meshgrid(*[LUT_PARAMS[k] for k in param_names], indexing='ij')

    # 生成索引网格
    index_mesh = np.indices(mesh[0].shape)
    total_points = np.prod(mesh[0].shape)

    # 准备任务参数
    params_list = []
    for idx in np.ndindex(mesh[0].shape):
        params = [mesh[i][idx] for i in range(len(mesh))]
        params.append(idx)  # 添加索引位置
        params_list.append(params)

    # 配置并行参数
    num_cores = multiprocessing.cpu_count()
    max_workers = min(4, num_cores)  # 限制每个LUT的并行度

    # 使用进程池并行计算
    start_time = time.time()
    try:
        with ProcessPoolExecutor(
                max_workers=max_workers,
                initializer=init_worker,
                initargs=(shm.name, lut_shape, LUT_PARAMS['bands'])
        ) as executor:
            # 提交任务
            futures = {}
            for params in params_list:
                # 提取索引位置（最后一个元素）
                idx_tuple = params[-1]
                # 提交任务，传入固定AOT和臭氧值
                future = executor.submit(
                    calculate_point,
                    params,
                    lucc_value,
                    profile_type,
                    aot_value,  # 固定AOT值
                    ozone_value  # 固定臭氧值
                )
                futures[future] = idx_tuple

            # 处理结果并显示进度
            completed = 0
            for future in as_completed(futures):
                try:
                    future.result()
                    completed += 1
                    if completed % 5 == 0 or completed == total_points:
                        elapsed = time.time() - start_time
                        remaining = (total_points - completed) * (elapsed / completed) if completed > 0 else 0
                        print(f"[{timestamp()}] [LUT] 进度: {completed}/{total_points} "
                              f"({completed / total_points * 100:.1f}%) - 剩余: {remaining:.0f}s")
                except Exception as e:
                    print(f"[{timestamp()}] [ERROR] 计算失败: {str(e)}")
    except Exception as e:
        print(f"[{timestamp()}] [ERROR] 并行计算失败: {str(e)}")
        # 清理共享内存
        shm.close()
        shm.unlink()
        raise

    # 从共享内存复制结果
    lut_data = np.copy(shared_array)

    # 清理共享内存
    shm.close()
    shm.unlink()

    # 保存LUT
    ds = nc.Dataset(lut_file, 'w')

    # 保存固定参数作为全局属性
    ds.setncattr('fixed_aot550', aot_value)
    ds.setncattr('fixed_ozone', ozone_value)

    # 保存维度变量
    for dim_name in ['solar_zenith', 'view_zenith', 'relative_azimuth', 'water', 'toa_reflectance']:
        dim = ds.createDimension(dim_name, len(LUT_PARAMS[dim_name]))
        var = ds.createVariable(dim_name, 'f4', (dim_name,))
        var[:] = LUT_PARAMS[dim_name]

    band_dim = ds.createDimension('band', len(LUT_PARAMS['bands']))
    band_var = ds.createVariable('band', 'f4', ('band',))
    band_var[:] = LUT_PARAMS['bands']

    sr_var = ds.createVariable('sr', 'f4', tuple(param_names) + ('band',))
    sr_var[:] = lut_data
    ds.close()

    print(f"[{timestamp()}] [LUT] LUT切片已保存: {lut_file}")
    return lut_key, lut_data


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
        ("solar_zenith", "度", len(LUT_PARAMS['solar_zenith'])),
        ("view_zenith", "度", len(LUT_PARAMS['view_zenith'])),
        ("relative_azimuth", "度", len(LUT_PARAMS['relative_azimuth'])),
        ("aot550", "无单位", len(LUT_PARAMS['aot550'])),
        ("water", "g/cm²", len(LUT_PARAMS['water'])),
        ("ozone", "cm-atm", len(LUT_PARAMS['ozone'])),
        ("toa_reflectance", "无单位", len(LUT_PARAMS['toa_reflectance']))
    ]

    for param, unit, points in params_info:
        values = LUT_PARAMS[param]
        print("{:<20} {:<15.4f} {:<15.4f} {:<10} {:<10}".format(
            param, min(values), max(values), points, unit))

    print("=" * 70)
    print(f"波段: {LUT_PARAMS['bands']} (μm)")
    print(f"LUCC类别: {LUCC_CATEGORIES}")
    print("=" * 70)


def initialize_lut_params():
    """初始化LUT参数网格（幂等操作）"""
    global LUT_PARAMS, OPTIMIZED_PARAMS, LUCC_CATEGORIES, LUT_PARAMS_INITIALIZED

    # 避免重复初始化
    if LUT_PARAMS_INITIALIZED:
        return

    # 加载参数统计
    stats = load_parameter_statistics()
    OPTIMIZED_PARAMS, LUCC_CATEGORIES = setup_optimized_params(stats)

    # 确保所有必要键都存在 - 修正键名
    required_keys = ['solar_zenith', 'view_zenith', 'relative_azimuth',
                     'aot550', 'water', 'ozone', 'toa_reflectance_band03']

    for key in required_keys:
        if key not in OPTIMIZED_PARAMS:
            print(f"[{timestamp()}] [WARN] 使用默认值填充缺失参数: {key}")
            # 设置更合理的默认值
            if 'zenith' in key:
                OPTIMIZED_PARAMS[key] = (0, 90)
            elif 'azimuth' in key:
                OPTIMIZED_PARAMS[key] = (0, 180)
            elif 'aot' in key:
                OPTIMIZED_PARAMS[key] = (0.01, 3)
            elif 'water' in key:
                OPTIMIZED_PARAMS[key] = (0.1, 5)
            elif 'ozone' in key:
                OPTIMIZED_PARAMS[key] = (0.1, 0.5)
            elif 'reflectance' in key:
                OPTIMIZED_PARAMS[key] = (0.01, 0.99)

    # 设置LUT网格参数
    LUT_PARAMS = {
        'solar_zenith': np.linspace(OPTIMIZED_PARAMS['solar_zenith'][0],
                                    OPTIMIZED_PARAMS['solar_zenith'][1], 12),
        'view_zenith': np.linspace(OPTIMIZED_PARAMS['view_zenith'][0],
                                   OPTIMIZED_PARAMS['view_zenith'][1], 10),
        'relative_azimuth': np.linspace(OPTIMIZED_PARAMS['relative_azimuth'][0],
                                        OPTIMIZED_PARAMS['relative_azimuth'][1], 12),
        # 正确定义AOT550和臭氧值
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
            (OPTIMIZED_PARAMS['ozone'][0] + OPTIMIZED_PARAMS['ozone'][1]) / 2,
            OPTIMIZED_PARAMS['ozone'][1]
        ]),
        # 使用 band03 的反射率范围
        'toa_reflectance': np.linspace(OPTIMIZED_PARAMS['toa_reflectance_band03'][0],
                                       OPTIMIZED_PARAMS['toa_reflectance_band03'][1], 10),
        'bands': [0.64, 0.86]
    }
    LUT_PARAMS_INITIALIZED = True  # 标记已初始化



def init_outer_worker():
    """子进程初始化函数"""
    global LUT_PARAMS
    if not LUT_PARAMS:  # 确保在子进程中初始化
        initialize_lut_params()


def main():
    # 初始化LUT参数
    initialize_lut_params()

    # 命令行参数解析
    parser = argparse.ArgumentParser(description='生成LUT分片')
    parser.add_argument('--shard-id', type=int, default=0,
                        help='当前分片的ID (0到total-shards-1)')
    parser.add_argument('--total-shards', type=int, default=1,
                        help='总分片数')
    args = parser.parse_args()

    print(f"[{timestamp()}] 开始生成LUTs (分片 {args.shard_id}/{args.total_shards})")
    print_optimized_params()

    # 获取所有可能的组合：LUCC × 大气廓线 × AOT550 × 臭氧
    tasks = []
    unique_profiles = get_unique_profiles()  # 正确定义unique_profiles
    aot_values = LUT_PARAMS['aot550']  # 获取AOT550的取值
    ozone_values = LUT_PARAMS['ozone']  # 获取臭氧的取值

    for lucc_value in LUCC_CATEGORIES:
        for profile in unique_profiles:
            for aot in aot_values:
                for ozone in ozone_values:
                    tasks.append((profile, lucc_value, aot, ozone))

    # 分片逻辑
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
    # 减少外层并行度
    max_outer_workers = max(1, multiprocessing.cpu_count() // 4)
    with ProcessPoolExecutor(
            max_workers=max_outer_workers,
            initializer=init_outer_worker
    ) as executor:
        futures = {executor.submit(create_lut, *task): task for task in tasks}

        for future in as_completed(futures):
            try:
                lut_key, _ = future.result()
                completed += 1
                print(f"[{timestamp()}] [{completed}/{len(tasks)}] LUT切片完成: {lut_key}")
            except Exception as e:
                print(f"[{timestamp()}] [ERROR] LUT切片生成失败: {str(e)}")

    print(f"[{timestamp()}] 分片 {args.shard_id}/{args.total_shards} 完成")


if __name__ == "__main__":
    # 设置多进程启动方法
    multiprocessing.set_start_method('spawn', force=True)
    main()