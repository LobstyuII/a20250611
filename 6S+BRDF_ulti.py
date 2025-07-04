import os
import time
import netCDF4 as nc
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed
from Py6S import *

# 更新路径配置
PATHS = {
    "hourly_toa": "D:/H8_data/Hourly_TOA_Angles/",
    "merra2": "D:/H8_data/MERRA2/",
    "lucc": "D:/H8_data/LC_2015_2024.nc",
    "output": "D:/H8_Data/H8SR/",
    "luts": "D:/H8_data/LUTs.nc",
    "aod": "D:/H8_data/H8L3ARP/"
}

# 只使用前4个波段
BAND_WAVELENGTHS = [0.47, 0.51, 0.64, 0.86]
BAND_NAMES = [f"Albedo_0{i + 1}" for i in range(0, 4)]
ANGLE_NAMES = ['SAZ', 'SAA', 'SOZ', 'SOA']

# 日期范围
START_DATE = datetime(2015, 7, 7)
END_DATE = datetime(2016, 12, 31)

# 只处理白天的小时 (0-12时和21-23时)
PROCESS_HOURS = list(range(0, 13)) + list(range(21, 24))

# LUCC到BRDF参数的映射
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


def get_current_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def calculate_data_validity(data_array):
    """计算数据有效性比例"""
    if data_array.size == 0:
        return 0, 0, 0.0
    total = data_array.size
    valid = np.count_nonzero(~np.isnan(data_array))
    return valid, total, valid / total if total > 0 else 0.0


def load_netcdf_data(file_path, variables):
    """高效加载NetCDF文件数据，处理掩码值"""
    if not os.path.exists(file_path):
        return None

    try:
        with nc.Dataset(file_path) as ds:
            data = {}
            for var in variables:
                if var == 'Station':
                    var_data = ds.variables[var][:]
                    # 处理不同格式的站点数据
                    if var_data.dtype.kind == 'S':  # 字节字符串
                        data[var] = [s.tobytes().decode('utf-8').strip() for s in var_data]
                    elif var_data.dtype.kind == 'U':  # Unicode字符串
                        data[var] = [s.strip() for s in var_data]
                    else:  # 其他类型
                        data[var] = [str(s).strip() for s in var_data]
                else:
                    var_data = ds.variables[var][:]
                    if isinstance(var_data, np.ma.MaskedArray):
                        var_data = var_data.filled(np.nan)
                    data[var] = var_data
            return data
    except Exception as e:
        print(f"[{get_current_timestamp()}] Error loading {file_path}: {str(e)}")
        return None


def set_brdf_model(s, lucc_value):
    """根据LUCC类型设置BRDF模型"""
    brdf_params = LUCC_TO_BRDF.get(int(lucc_value), LUCC_TO_BRDF[255])

    if brdf_params["model"] == "Rahman":
        s.ground_reflectance = GroundReflectance.HomogeneousRahman(
            intensity=brdf_params["intensity"],
            asymmetry_factor=brdf_params["asymmetry"],
            structural_parameter=brdf_params["structural"]
        )
    elif brdf_params["model"] == "Walthall":
        s.ground_reflectance = GroundReflectance.HomogeneousWalthall(
            param1=brdf_params["param1"],
            param2=brdf_params["param2"],
            param3=brdf_params["param3"],
            albedo=brdf_params["albedo"]
        )
    else:
        s.ground_reflectance = GroundReflectance.HomogeneousLambertian(brdf_params["albedo"])
    return s


def calculate_general_availability(hourly_avail):
    """根据小时可用性标志确定综合可用性"""
    return 1 if hourly_avail != 0 else 0


def convert_merra2_units(to3, tqv):
    """转换MERRA2单位到Py6S所需单位，处理NaN值"""
    if np.isnan(to3) or np.isnan(tqv):
        return np.nan, np.nan

    ozone_cmatm = to3 * 0.001  # Dobson -> cm-atm
    water_gcm2 = tqv * 0.1  # kg/m² -> g/cm²
    return ozone_cmatm, water_gcm2


def convert_aot500_to_aot550(aot500, angstrom_exponent=1.3):
    """将500nm AOT转换为550nm AOT"""
    if np.isnan(aot500) or aot500 < 0:
        return np.nan
    return aot500 * (500 / 550) ** angstrom_exponent


def process_station(station_data):
    """处理单个站点的数据"""
    station, idx, hourly_data, merra2_data, aod_data, lucc_dict, station_coords, date = station_data
    lat, lon = station_coords.get(station, (np.nan, np.nan))
    # 计算综合可用性
    hourly_avail = hourly_data['hourly_availability'][idx]
    gen_avail = calculate_general_availability(hourly_avail)

    if gen_avail == 1:
        return station, gen_avail, np.full(len(BAND_WAVELENGTHS), np.nan), 0

    # 获取大气参数并转换单位
    to3 = merra2_data['TO3'][idx] if 'TO3' in merra2_data and idx < len(merra2_data['TO3']) else np.nan
    tqv = merra2_data['TQV'][idx] if 'TQV' in merra2_data and idx < len(merra2_data['TQV']) else np.nan
    ozone_cmatm, water_gcm2 = convert_merra2_units(to3, tqv)

    # 获取AOD数据
    aot500 = aod_data['AOT'][idx] if 'AOT' in aod_data and idx < len(aod_data['AOT']) else np.nan
    data_avail = aod_data['Data_Availability'][idx] if 'Data_Availability' in aod_data and idx < len(
        aod_data['Data_Availability']) else 1
    aot550 = convert_aot500_to_aot550(aot500) if data_avail == 0 and not np.isnan(aot500) and aot500 >= 0 else np.nan

    # 获取角度数据
    saz = hourly_data['SAZ'][idx] if 'SAZ' in hourly_data and idx < len(hourly_data['SAZ']) else np.nan
    saa = hourly_data['SAA'][idx] if 'SAA' in hourly_data and idx < len(hourly_data['SAA']) else np.nan
    soz = hourly_data['SOZ'][idx] if 'SOZ' in hourly_data and idx < len(hourly_data['SOZ']) else np.nan
    soa = hourly_data['SOA'][idx] if 'SOA' in hourly_data and idx < len(hourly_data['SOA']) else np.nan

    # 关键修复：将H8的Albedo转换为TOA反射率
    # H8的"Albedo"实际上是reflectance * cos(SOZ)，我们需要原始TOA反射率
    toa_reflectances = []
    if not np.isnan(soz):
        # 计算cos(SOZ)，确保不小于0.01
        cos_soz = max(np.cos(np.radians(soz)), 0.01)

        for band in BAND_NAMES:
            if band in hourly_data and idx < len(hourly_data[band]):
                albedo_val = hourly_data[band][idx]
                # 转换为原始TOA反射率
                toa_refl = albedo_val / cos_soz
                # 限制在合理范围内
                if toa_refl > 1.0:
                    toa_refl = 1.0
                elif toa_refl < 0.0:
                    toa_refl = 0.0
                toa_reflectances.append(toa_refl)
            else:
                toa_reflectances.append(np.nan)
    else:
        toa_reflectances = [np.nan] * len(BAND_NAMES)

    # 获取LUCC类型
    lucc_value = lucc_dict.get(station, 255)

    # 执行6S大气校正+BRDF归一化
    sr_results = np.full(len(BAND_WAVELENGTHS), np.nan, dtype=np.float32)
    valid_flag = 0

    try:
        # 创建6S对象
        s = SixS()
        s.geometry = Geometry.User()

        # 关键修复：确保角度单位正确
        # 6S要求天顶角范围0-90度（0为天顶，90为地平线），方位角0-360度（0为北，顺时针增加）
        # H8数据符合此标准，直接使用

        # 设置几何参数
        s.geometry.solar_z = soz  # 太阳天顶角（度）
        s.geometry.solar_a = soa  # 太阳方位角（度）
        s.geometry.view_z = saz  # 观测天顶角（度）
        s.geometry.view_a = saa  # 观测方位角（度）

        # 设置大气参数
        if not np.isnan(water_gcm2) and not np.isnan(ozone_cmatm) and water_gcm2 > 0 and ozone_cmatm > 0:
            s.atmos_profile = AtmosProfile.UserWaterAndOzone(water=water_gcm2, ozone=ozone_cmatm)
        elif not np.isnan(lat):
            # 根据纬度选择最近的大气廓线
            if -30 <= lat <= 30:
                s.atmos_profile = AtmosProfile.PredefinedType(AtmosProfile.Tropical)
            elif 30 < lat <= 60:
                if date.month in [5, 6, 7, 8, 9]:
                    s.atmos_profile = AtmosProfile.PredefinedType(AtmosProfile.MidlatitudeSummer)
                else:
                    s.atmos_profile = AtmosProfile.PredefinedType(AtmosProfile.MidlatitudeWinter)
            else:
                if date.month in [5, 6, 7, 8, 9]:
                    s.atmos_profile = AtmosProfile.PredefinedType(AtmosProfile.SubarcticSummer)
                else:
                    s.atmos_profile = AtmosProfile.PredefinedType(AtmosProfile.SubarcticWinter)
        else:
            s.atmos_profile = AtmosProfile.PredefinedType(AtmosProfile.MidlatitudeSummer)

        # 设置气溶胶参数
        s.aero_profile = AeroProfile.PredefinedType(AeroProfile.Continental)
        if not np.isnan(aot550) and aot550 >= 0:
            s.aot550 = aot550

        # 设置BRDF模型
        s = set_brdf_model(s, lucc_value)

        # 处理每个波段
        for band_idx, (wavelength, toa_refl) in enumerate(zip(BAND_WAVELENGTHS, toa_reflectances)):
            if np.isnan(toa_refl) or toa_refl < 0 or toa_refl > 1:
                continue

            try:
                s.wavelength = Wavelength(wavelength)
                s.atmos_corr = AtmosCorr.AtmosCorrBRDFFromReflectance(reflectance=toa_refl)
                s.run()
                sr_results[band_idx] = s.outputs.pixel_reflectance
            except Exception:
                # 波段处理错误不影响其他波段
                sr_results[band_idx] = np.nan

        valid_flag = 1
    except Exception as e:
        print(f"[{get_current_timestamp()}] Error processing station {station}: {str(e)}")
        pass

    return station, gen_avail, sr_results, valid_flag


# 以下函数保持不变（load_lucc_data, load_station_coords, process_hour, main等）
# 为节省篇幅，这里省略了未修改的函数部分，实际使用时请保留原代码中的这些函数

def process_hour(date, hour, stations_list, lucc_dict, station_coords):
    """处理单个小时的数据"""
    date_str = date.strftime("%Y%m%d")
    hour_str = f"{hour * 100:04d}"  # 修正时间格式
    time_key = f"{date_str}_{hour_str}"

    # 构建文件路径
    hourly_toa_file = os.path.join(PATHS["hourly_toa"], date_str[:4], date_str[4:6],
                                   f"H8_hourly_TOA_angles_{time_key}.nc")
    merra2_file = os.path.join(PATHS["merra2"], date_str[:4], date_str[4:6],
                               f"MERRA2_{time_key}_TO3_TQV.nc")
    aod_file = os.path.join(PATHS["aod"], date_str[:4], date_str[4:6], f"H8L3ARP_{time_key}.nc")
    output_file = os.path.join(PATHS["output"], f"SR_{time_key}.nc")

    # 检查输出文件是否已存在
    if os.path.exists(output_file):
        print(f"[{get_current_timestamp()}] [SKIPPED] Output file already exists: {output_file}")
        return output_file, (0, 0, 0.0)

    # 检查输入文件是否存在
    files_exist = [os.path.exists(hourly_toa_file), os.path.exists(merra2_file), os.path.exists(aod_file)]
    if not all(files_exist):
        print(f"[{get_current_timestamp()}] [SKIPPED] Missing files for {time_key}")
        return None, (0, 0, 0.0)

    # 加载数据
    hourly_data = load_netcdf_data(hourly_toa_file, ['Station'] + BAND_NAMES + ANGLE_NAMES + ['hourly_availability'])
    merra2_data = load_netcdf_data(merra2_file, ['Station', 'TO3', 'TQV'])
    aod_data = load_netcdf_data(aod_file, ['Station', 'AOT', 'Data_Availability'])

    if None in [hourly_data, merra2_data, aod_data]:
        print(f"[{get_current_timestamp()}] [ERROR] Failed to load data for {time_key}")
        return None, (0, 0, 0.0)

    # 创建站点索引映射
    station_idx_map = {station: idx for idx, station in enumerate(hourly_data['Station'])}
    matched_stations = [s for s in stations_list if s in station_idx_map]

    # 处理站点数据
    sr_results = np.full((len(stations_list), len(BAND_WAVELENGTHS)), np.nan, dtype=np.float32)
    gen_avail = np.full(len(stations_list), -1, dtype=np.int8)
    valid_flags = np.zeros(len(stations_list), dtype=np.int8)
    station_index_map = {station: idx for idx, station in enumerate(stations_list)}

    valid_count = 0
    total_stations = len(matched_stations)

    for station in matched_stations:
        idx = station_idx_map[station]
        task = (station, idx, hourly_data, merra2_data, aod_data, lucc_dict, station_coords, date)
        station, gen, sr, valid = process_station(task)

        if station in station_index_map:
            sidx = station_index_map[station]
            gen_avail[sidx] = gen
            sr_results[sidx] = sr
            valid_flags[sidx] = valid
            if valid == 1:
                valid_count += 1

    # 保存结果
    try:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with nc.Dataset(output_file, 'w') as ds:
            # 创建维度
            ds.createDimension('station', len(stations_list))

            # 创建站点变量
            station_var = ds.createVariable('Station', str, ('station',))
            station_var[:] = np.array(stations_list, dtype=object)

            # 创建可用性变量
            gen_avail_var = ds.createVariable('General_availability', np.int8, ('station',))
            gen_avail_var[:] = gen_avail

            # 创建有效性标志变量
            valid_var = ds.createVariable('valid_flag', np.int8, ('station',))
            valid_var[:] = valid_flags

            # 创建每个波段作为单独的变量
            for band_idx, band_name in enumerate(BAND_NAMES):
                band_var = ds.createVariable(band_name, np.float32, ('station',))
                band_var[:] = sr_results[:, band_idx]
                band_var.units = "reflectance"
                band_var.description = f"Surface reflectance for band {band_name} ({BAND_WAVELENGTHS[band_idx]}μm)"

            # 添加全局属性
            ds.date_created = get_current_timestamp()
            ds.title = 'Himawari-8 Surface Reflectance Product'
            ds.time = hour_str
            ds.date = date_str
            ds.source = "6S atmospheric correction with BRDF normalization"
            ds.author = "H8SR Processing System"

        valid_ratio = valid_count / total_stations if total_stations > 0 else 0
        print(
            f"[{get_current_timestamp()}] [SUCCESS] Generated {output_file} - Valid stations: {valid_count}/{total_stations} ({valid_ratio:.2%})")
        return output_file, (valid_count, total_stations, valid_ratio)
    except Exception as e:
        print(f"[{get_current_timestamp()}] [ERROR] Failed to save {output_file}: {str(e)}")
        return None, (0, 0, 0.0)


def load_lucc_data():
    """加载LUCC数据到内存"""
    lucc_file = PATHS["lucc"]
    if not os.path.exists(lucc_file):
        print(f"[{get_current_timestamp()}] [ERROR] LUCC file not found: {lucc_file}")
        return None

    try:
        with nc.Dataset(lucc_file) as ds:
            station_var = ds.variables['Station']
            station_data = station_var[:]
            # 处理不同格式的站点数据
            if station_data.dtype.kind == 'S':  # 字节字符串
                stations = [s.tobytes().decode('utf-8').strip() for s in station_data]
            elif station_data.dtype.kind == 'U':  # Unicode字符串
                stations = [s.strip() for s in station_data]
            else:  # 其他类型
                stations = [str(s).strip() for s in station_data]

            lucc_values = ds.variables['LC_type1'][-1, :]  # 使用最新年份的数据

            if isinstance(lucc_values, np.ma.MaskedArray):
                lucc_values = lucc_values.filled(255)

            return dict(zip(stations, lucc_values))
    except Exception as e:
        print(f"[{get_current_timestamp()}] [ERROR] Failed to load LUCC data: {str(e)}")
        return None


def load_station_coords():
    """从LUTs.nc文件加载站点经纬度信息"""
    luts_file = PATHS["luts"]
    if not os.path.exists(luts_file):
        print(f"[{get_current_timestamp()}] [ERROR] LUTs file not found: {luts_file}")
        return {}

    try:
        with nc.Dataset(luts_file) as ds:
            station_var = ds.variables['Station']
            station_data = station_var[:]
            # 处理不同格式的站点数据
            if station_data.dtype.kind == 'S':  # 字节字符串
                stations = [s.tobytes().decode('utf-8').strip() for s in station_data]
            elif station_data.dtype.kind == 'U':  # Unicode字符串
                stations = [s.strip() for s in station_data]
            else:  # 其他类型
                stations = [str(s).strip() for s in station_data]

            # 使用正确的变量名 'Lat' 和 'Lon'
            lats = ds.variables['Lat'][:]
            lons = ds.variables['Lon'][:]

            # 转换为numpy数组并处理掩码值
            if isinstance(lats, np.ma.MaskedArray):
                lats = lats.filled(np.nan)
            if isinstance(lons, np.ma.MaskedArray):
                lons = lons.filled(np.nan)

            return {station: (lat, lon) for station, lat, lon in zip(stations, lats, lons)}
    except Exception as e:
        print(f"[{get_current_timestamp()}] [ERROR] Failed to load station coordinates: {str(e)}")
        return {}


def main():
    """主函数：并行处理日期范围"""
    start_time = time.time()
    print(f"[{get_current_timestamp()}] [START] Processing started")

    # 创建输出目录
    os.makedirs(PATHS["output"], exist_ok=True)

    # 加载站点坐标
    print(f"[{get_current_timestamp()}] [INFO] Loading station coordinates...")
    station_coords = load_station_coords()
    if not station_coords:
        print(f"[{get_current_timestamp()}] [ERROR] Failed to load station coordinates. Exiting.")
        return
    stations_list = list(station_coords.keys())
    print(f"[{get_current_timestamp()}] [INFO] Loaded {len(stations_list)} stations")

    # 加载LUCC数据
    print(f"[{get_current_timestamp()}] [INFO] Loading LUCC data...")
    lucc_dict = load_lucc_data()
    if lucc_dict is None:
        print(f"[{get_current_timestamp()}] [ERROR] Failed to load LUCC data. Exiting.")
        return

    # 生成日期列表
    date_list = []
    current_date = START_DATE
    while current_date <= END_DATE:
        date_list.append(current_date)
        current_date += timedelta(days=1)

    print(
        f"[{get_current_timestamp()}] [INFO] Processing {len(date_list)} days from {START_DATE.date()} to {END_DATE.date()}")
    print(f"[{get_current_timestamp()}] [INFO] Processing hours: {PROCESS_HOURS}")

    # 准备所有任务
    tasks = []
    for date in date_list:
        for hour in PROCESS_HOURS:
            tasks.append((date, hour, stations_list, lucc_dict, station_coords))

    print(f"[{get_current_timestamp()}] [INFO] Total tasks: {len(tasks)}")

    # 使用多进程处理
    processed_files = []
    total_valid = 0
    total_stations = 0

    # 使用进程池
    max_workers = max(1, os.cpu_count() // 2)
    max_workers = 8

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for task in tasks:
            date, hour, stations_list, lucc_dict, station_coords = task
            future = executor.submit(process_hour, date, hour, stations_list, lucc_dict, station_coords)
            futures[future] = (date, hour)

        # 处理完成的任务
        for future in as_completed(futures):
            date, hour = futures[future]
            date_str = date.strftime("%Y%m%d")
            hour_str = f"{hour * 100:04d}"
            time_key = f"{date_str}_{hour_str}"

            try:
                output_file, (valid, total, ratio) = future.result()
                if output_file:
                    processed_files.append(output_file)
                    total_valid += valid
                    total_stations += total
                    print(
                        f"[{get_current_timestamp()}] [COMPLETED] Processed {time_key}: {valid}/{total} valid ({ratio:.2%})")
                else:
                    print(f"[{get_current_timestamp()}] [FAILED] Failed to process {time_key}")
            except Exception as e:
                print(f"[{get_current_timestamp()}] [ERROR] Error processing {time_key}: {str(e)}")

    # 最终统计
    total_ratio = total_valid / total_stations if total_stations > 0 else 0
    total_time = (time.time() - start_time) / 3600  # 转换为小时

    print(f"\n[{get_current_timestamp()}] [SUMMARY] Processing completed")
    print(f"  Processed time points: {len(processed_files)}")
    print(f"  Total stations processed: {total_stations}")
    print(f"  Valid stations: {total_valid} ({total_ratio:.2%})")
    print(f"  Total processing time: {total_time:.2f} hours")


if __name__ == "__main__":
    main()