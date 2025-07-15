import os
import time
import netCDF4 as nc
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed
import numba as nb
import json

# ======================== 可配置参数 ========================
# 路径配置
PATHS = {
    "hourly_toa": "D:/H8_data/Hourly_TOA_Angles/",
    "merra2": "D:/H8_data/MERRA2/",
    "merra2_aot550": "D:/H8_data/MERRA2_AOT550/",
    "lucc": "D:/H8_data/LC_2015_2024.nc",
    "output": "D:/H8_Data/H8SR/",
    "luts": "D:/H8_data/LUTs.nc",
    "lut_cache": "D:/H8_data/LUT_Cache/",
    "task_log": "D:/H8_data/task_status.json"  # 任务状态记录
}

# 处理范围（根据主机分配任务）
START_DATE = datetime(2015, 7, 7)
END_DATE = datetime(2021, 12, 31)
PROCESS_HOURS = list(range(0, 13)) + list(range(21, 24))

# 主机任务分配（示例：主机1处理前半部分，主机2处理后半部分）
HOST_ID = 1  # 当前主机ID
TOTAL_HOSTS = 2  # 总主机数

# 处理参数
BAND_NAMES = ["Albedo_03", "Albedo_04"]  # 仅处理两个波段
BATCH_SIZE = 100  # 站点批处理大小
MAX_WORKERS = 4  # 最大并行进程数
# ========================================================

# 初始化目录
os.makedirs(PATHS["output"], exist_ok=True)
os.makedirs(os.path.dirname(PATHS["task_log"]), exist_ok=True)


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_task_status():
    """加载任务状态"""
    if os.path.exists(PATHS["task_log"]):
        try:
            with open(PATHS["task_log"], 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_task_status(status):
    """保存任务状态"""
    with open(PATHS["task_log"], 'w') as f:
        json.dump(status, f)


def get_brdf_params(lucc_value):
    """获取BRDF参数（简化版）"""
    lucc_int = int(lucc_value)
    # 简化的BRDF映射
    brdf_map = {
        1: {"model": "Rahman", "intensity": 0.3, "asymmetry": 0.1, "structural": 0.5},
        # ...（其他映射）...
        255: {"model": "Lambertian", "albedo": 0.2}
    }
    return brdf_map.get(lucc_int, brdf_map[255])


def load_lut(lut_key):
    """加载LUT文件"""
    lut_file = os.path.join(PATHS["lut_cache"], f"{lut_key}.nc")
    if not os.path.exists(lut_file):
        print(f"[{timestamp()}] [ERROR] LUT文件不存在: {lut_file}")
        return None

    with nc.Dataset(lut_file) as ds:
        lut_data = ds['sr'][:]
        # 获取维度范围用于边界检查
        dim_ranges = [ds.dimensions[dim].size for dim in [
            'solar_zenith', 'view_zenith', 'relative_azimuth',
            'aot550', 'water', 'ozone', 'toa_reflectance'
        ]]
        return lut_data, dim_ranges


@nb.njit(parallel=True)
def vectorized_lookup(lut, indices, dim_ranges):
    """带边界检查的LUT查询"""
    results = np.full((indices.shape[0], lut.shape[-1]), np.nan, dtype=np.float32)

    for i in nb.prange(indices.shape[0]):
        idx_tuple = tuple(indices[i, j] for j in range(7))  # 7个维度

        # 边界检查（关键改进）
        valid = True
        for dim in range(7):
            idx = idx_tuple[dim]
            if idx < 0 or idx >= dim_ranges[dim]:
                valid = False
                break

        if valid:
            for band in range(lut.shape[-1]):
                val = lut[idx_tuple + (band,)]
                # 检查是否为填充值
                if not np.isnan(val) and val != -9999.0:
                    results[i, band] = val
    return results


def process_hourly_data(date, hour):
    """处理单小时数据"""
    date_str = date.strftime("%Y%m%d")
    hour_str = f"{hour * 100:04d}"
    time_key = f"{date_str}_{hour_str}"
    output_file = os.path.join(PATHS["output"], f"SR_{time_key}.nc")

    # 检查是否已完成
    if os.path.exists(output_file):
        print(f"[{timestamp()}] [SKIP] 文件已存在: {output_file}")
        return time_key, True

    # 加载输入数据（简化示例）
    # 实际实现中需加载TOA、MERRA2等数据
    try:
        # ===== 数据处理核心逻辑 =====
        # 1. 加载站点数据
        # 2. 计算大气参数
        # 3. 使用LUT计算地表反射率
        # 4. 保存结果

        # 模拟处理过程
        print(f"[{timestamp()}] [PROCESS] 处理: {time_key}")
        time.sleep(10)  # 模拟处理时间

        # 创建结果文件
        with nc.Dataset(output_file, 'w') as ds:
            ds.createDimension('station', 100)
            ds.createVariable('SR', 'f4', ('station', 'band'))[:] = np.random.rand(100, 2)
            ds.time = time_key
        # ===========================

        print(f"[{timestamp()}] [SUCCESS] 完成: {time_key}")
        return time_key, True
    except Exception as e:
        print(f"[{timestamp()}] [ERROR] 处理失败 {time_key}: {str(e)}")
        # 删除不完整的输出文件
        if os.path.exists(output_file):
            os.remove(output_file)
        return time_key, False


def main():
    """主处理函数"""
    print(f"[{timestamp()}] 开始数据处理")

    # 加载任务状态
    task_status = load_task_status()

    # 生成任务列表
    all_tasks = []
    current_date = START_DATE
    while current_date <= END_DATE:
        for hour in PROCESS_HOURS:
            time_key = f"{current_date.strftime('%Y%m%d')}_{hour * 100:04d}"
            # 检查任务状态
            if task_status.get(time_key) != "completed":
                all_tasks.append((current_date, hour))
        current_date += timedelta(days=1)

    # 主机任务分配
    total_tasks = len(all_tasks)
    tasks_per_host = total_tasks // TOTAL_HOSTS
    start_idx = (HOST_ID - 1) * tasks_per_host
    end_idx = start_idx + tasks_per_host if HOST_ID < TOTAL_HOSTS else total_tasks

    host_tasks = all_tasks[start_idx:end_idx]
    print(f"[{timestamp()}] 主机 {HOST_ID}/{TOTAL_HOSTS} 分配任务: {len(host_tasks)}/{total_tasks}")

    # 处理任务
    completed_count = 0
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_hourly_data, date, hour): (date, hour)
                   for date, hour in host_tasks}

        for future in as_completed(futures):
            date, hour = futures[future]
            time_key, success = future.result()

            # 更新任务状态
            task_status[time_key] = "completed" if success else "failed"
            save_task_status(task_status)

            if success:
                completed_count += 1

            print(f"[{timestamp()}] 进度: {completed_count}/{len(host_tasks)} "
                  f"({completed_count / len(host_tasks) * 100:.1f}%)")

    print(f"[{timestamp()}] 数据处理完成")


if __name__ == "__main__":
    main()