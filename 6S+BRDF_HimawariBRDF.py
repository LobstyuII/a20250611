import os
import time
import netCDF4 as nc
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed
from Py6S import *
from multiprocessing import shared_memory
import multiprocessing
import traceback
import gc
import pyarrow as pa
import pyarrow.parquet as pq

PATHS = {
    "hourly_sozSR": "D:/H8_data/Hourly_sozSR_Angles/",
    "merra2_slv": "D:/H8_data/MERRA2_slv/",
    "merra2_aer": "D:/H8_data/MERRA2_aer/",
    "lucc": "D:/H8_data/LC_2015_2024.nc",
    "luts": "D:/H8_data/LUTs.nc",
    "output_h8sr": "D:/H8_data/H8SR/",
    "himawari_brdf": "D:/H8_data/Himawari_BRDF_Albedo",
    "output_parquet": "D:/H8_data/Correction_Records/"
}

# 波段配置
BAND_WAVELENGTHS = [0.64, 0.86]
BAND_NAMES = ['Albedo_03', 'Albedo_04']
ANGLE_NAMES = ['SAZ', 'SAA', 'SOZ', 'SOA']

# 处理范围
START_DATE = datetime(2015, 7, 7)
END_DATE = datetime(2016, 7, 7)
PROCESS_HOURS = list(range(0, 12)) + list(range(21, 23))

# 大气廓线映射
LATITUDE_TO_PROFILE = {
    (-90, -30): {5: AtmosProfile.SubarcticWinter, 9: AtmosProfile.SubarcticSummer},
    (-30, 30): AtmosProfile.Tropical,
    (30, 60): {5: AtmosProfile.MidlatitudeWinter, 9: AtmosProfile.MidlatitudeSummer},
    (60, 90): {5: AtmosProfile.SubarcticWinter, 9: AtmosProfile.SubarcticSummer}
}

# 最大SOZ角度阈值
MAX_SOZ_ANGLE = 70


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_netcdf(file_path, variables):
    """高效加载NetCDF数据"""
    if not os.path.exists(file_path):
        print(f"[{timestamp()}] [WARNING] File not found: {file_path}")
        return None

    try:
        with nc.Dataset(file_path) as ds:
            data = {}
            for var in variables:
                if var not in ds.variables:
                    print(f"[{timestamp()}] [WARNING] Variable '{var}' not found in {file_path}")
                    data[var] = np.array([np.nan])
                    continue

                var_data = ds.variables[var][:]

                if var == 'Station':
                    if var_data.dtype.kind in ['S', 'U']:
                        data[var] = [str(s).strip() for s in var_data]
                    else:
                        data[var] = [str(s).strip() for s in var_data]
                else:
                    if isinstance(var_data, np.ma.MaskedArray):
                        var_data = var_data.filled(np.nan)

                    if var == 'AOT550':
                        var_data = np.where(var_data == -9999.0, np.nan, var_data)

                    data[var] = var_data
            return data
    except Exception as e:
        print(f"[{timestamp()}] [ERROR] Error loading {file_path}: {str(e)}")
        return None


def get_atmos_profile(lat, date):
    """根据纬度和日期获取大气廓线"""
    if np.isnan(lat):
        print(f"[{timestamp()}] [WARNING] Latitude is NaN, using default profile")
        return AtmosProfile.PredefinedType(AtmosProfile.MidlatitudeSummer)

    for (low, high), profile in LATITUDE_TO_PROFILE.items():
        if low <= lat < high:
            if isinstance(profile, dict):
                month_group = 5 if date.month in range(5, 10) else 9
                selected_profile = profile[month_group]
                return AtmosProfile.PredefinedType(selected_profile)
            else:
                return AtmosProfile.PredefinedType(profile)

    print(f"[{timestamp()}] [WARNING] No profile found for lat {lat}, using default")
    return AtmosProfile.PredefinedType(AtmosProfile.MidlatitudeSummer)


def convert_merra2_units(to3, tqv):
    """转换MERRA2单位"""
    if np.isnan(to3) or np.isnan(tqv):
        return np.nan, np.nan
    return to3 * 0.001, tqv * 0.1  # Dobson->cm-atm, kg/m²->g/cm²


def load_daily_brdf_data(date):
    """加载指定日期的MODIS BRDF参数并应用缩放因子"""
    date_str = date.strftime("%Y%m%d")
    year = date_str[:4]
    month = date_str[4:6]
    file_path = os.path.join(PATHS["himawari_brdf"], year, month, f"Himawari_adjusted_BRDF_Albedo_{date_str}.nc")

    if not os.path.exists(file_path):
        print(f"[{timestamp()}] [WARNING] Himawari BRDF file not found: {file_path}")
        return {}

    try:
        with nc.Dataset(file_path) as ds:
            # 读取站点和参数
            stations = [s.strip() for s in ds.variables['Station'][:]]
            params = {}
            param_names = ['Band1_iso', 'Band1_vol', 'Band1_geo', 'Band2_iso', 'Band2_vol', 'Band2_geo']

            for name in param_names:
                data = ds.variables[name][:]
                if isinstance(data, np.ma.MaskedArray):
                    data = data.filled(np.nan)
                # 替换无效值
                data[data == -9999.0] = np.nan
                # 应用缩放因子：乘以0.001
                data = data * 0.001
                params[name] = data

            # 构建站点到参数的映射
            brdf_dict = {}
            for idx, station in enumerate(stations):
                brdf_dict[station] = {
                    'Band1': (params['Band1_iso'][idx], params['Band1_vol'][idx], params['Band1_geo'][idx]),
                    'Band2': (params['Band2_iso'][idx], params['Band2_vol'][idx], params['Band2_geo'][idx])
                }
            return brdf_dict
    except Exception as e:
        print(f"[{timestamp()}] [ERROR] Failed to load MODIS BRDF: {str(e)}")
        return {}


def run_6s_correction(s, toa_ref, wavelength):
    """运行6S校正"""
    try:
        s.wavelength = Wavelength(wavelength)
        s.atmos_corr = AtmosCorr.AtmosCorrBRDFFromReflectance(toa_ref)
        s.run()
        return s.outputs.pixel_reflectance
    except Exception as e:
        print(f"[{timestamp()}] [WARNING] 6S correction failed: {str(e)}")
        return np.nan


def process_station_worker(task):
    """工作进程：处理单个站点并记录详细信息"""
    station, idx, hourly, merra2_slv, merra2_aer, coords, date, hour, result_idx, brdf_params = task
    lat, lon = coords.get(station, (np.nan, np.nan))

    # 初始化结果和记录字典
    sr_h8sr = np.full(len(BAND_WAVELENGTHS), np.nan, dtype=np.float32)
    gen_avail = 1
    valid_flag = 0

    # 初始化详细记录字典
    record = {
        'station': station,
        'date': date.strftime("%Y-%m-%d"),
        'hour': hour,
        'lat': lat,
        'lon': lon,
        'gen_avail': gen_avail,
        'valid_flag': valid_flag,
        'atmos_profile': 'Unknown',
        'brdf_model': 'MODIS',
        'error': None
    }

    # 添加角度信息
    for angle in ANGLE_NAMES:
        record[angle] = hourly.get(angle, [np.nan])[idx] if idx < len(hourly.get(angle, [])) else np.nan

    # 添加TOA反射率信息
    for band in BAND_NAMES:
        record[band] = hourly.get(band, [np.nan])[idx] if idx < len(hourly.get(band, [])) else np.nan

    try:
        # 检查数据可用性
        if hourly.get('hourly_availability', [1])[idx] != 0:
            record['error'] = 'Data unavailable'
            return (result_idx, gen_avail, sr_h8sr, valid_flag, record)

        gen_avail = 0
        record['gen_avail'] = gen_avail

        # 验证角度数据
        soz = record['SOZ']
        if any(np.isnan(record[a]) for a in ANGLE_NAMES) or soz > MAX_SOZ_ANGLE:
            record['error'] = f'Invalid angles: SOZ={soz}'
            return (result_idx, gen_avail, sr_h8sr, valid_flag, record)

        # 获取大气参数
        to3 = merra2_slv.get('TO3', [np.nan])[idx] if idx < len(merra2_slv.get('TO3', [])) else np.nan
        tqv = merra2_slv.get('TQV', [np.nan])[idx] if idx < len(merra2_slv.get('TQV', [])) else np.nan
        ozone, water = convert_merra2_units(to3, tqv)

        # 记录大气参数（原始和转换后）
        record.update({
            'TO3_raw': to3,
            'TQV_raw': tqv,
            'ozone_cm': ozone,
            'water_gcm2': water
        })

        # 获取AOT550值
        aot550 = merra2_aer.get('AOT550', [np.nan])[idx] if idx < len(merra2_aer.get('AOT550', [])) else np.nan
        record['AOT550'] = aot550

        # 检查MODIS BRDF参数是否存在
        if not brdf_params:
            record['error'] = 'Missing MODIS BRDF parameters'
            return (result_idx, gen_avail, sr_h8sr, valid_flag, record)

        # 计算TOA反射率
        cos_soz = np.cos(np.radians(soz))
        if cos_soz <= 0.01:
            cos_soz = 0.01

        toa_refs = []
        for i, band in enumerate(BAND_NAMES):
            albedo = record[band]
            if np.isnan(albedo) or albedo < 0 or albedo > 1:
                toa_ref = np.nan
            else:
                toa_ref = albedo
                toa_ref = np.clip(toa_ref, 0, 1)
            toa_refs.append(toa_ref)
            record[f'TOA_{band}'] = toa_ref  # 记录计算后的TOA反射率

        # 如果所有TOA反射率无效
        if all(np.isnan(r) for r in toa_refs):
            record['error'] = 'All TOA reflectance invalid'
            return (result_idx, gen_avail, sr_h8sr, valid_flag, record)

        # === 直接使用MODIS BRDF参数进行校正 ===
        s_brdf = SixS()
        try:
            s_brdf.altitudes.set_sensor_satellite_level()
            s_brdf.aero_profile = AeroProfile.PredefinedType(AeroProfile.Continental)

            # 设置几何参数
            s_brdf.geometry = Geometry.User()
            s_brdf.geometry.solar_z = record['SOZ']
            s_brdf.geometry.solar_a = record['SOA']
            s_brdf.geometry.view_z = record['SAZ']
            s_brdf.geometry.view_a = record['SAA']

            # 设置大气参数
            if not np.isnan(water) and not np.isnan(ozone) and water > 0 and ozone > 0:
                s_brdf.atmos_profile = AtmosProfile.UserWaterAndOzone(water, ozone)
                record['atmos_profile'] = 'UserWaterAndOzone'
            else:
                profile = get_atmos_profile(lat, date)
                s_brdf.atmos_profile = profile
                record['atmos_profile'] = str(profile).split('.')[-1]

            # 设置气溶胶
            if not np.isnan(aot550) and aot550 >= 0:
                s_brdf.aot550 = aot550

            # 运行BRDF校正
            for i, (wvl, refl) in enumerate(zip(BAND_WAVELENGTHS, toa_refs)):
                if np.isnan(refl) or refl < 0 or refl > 1:
                    continue

                # 确定当前波段对应的BRDF参数
                band_key = 'Band1' if i == 0 else 'Band2'
                band_params = brdf_params.get(band_key, (np.nan, np.nan, np.nan))
                iso, vol, geo = band_params

                # 检查参数有效性 - 如果有任一参数无效则跳过该波段
                if np.any(np.isnan([iso, vol, geo])):
                    record[f'error_band{i}'] = f'Invalid BRDF params for {band_key}: {iso}, {vol}, {geo}'
                    continue

                # 使用MODIS BRDF参数
                s_brdf.ground_reflectance = GroundReflectance.HomogeneousMODISBRDF(iso, vol, geo)

                # 运行6S校正
                try:
                    sr_h8sr[i] = run_6s_correction(s_brdf, refl, wvl)
                    record[f'SR_H8SR_{BAND_NAMES[i]}'] = sr_h8sr[i]
                except Exception as e:
                    record[f'error_band{i}'] = f'BRDF band {i} failed: {str(e)}'

        finally:
            del s_brdf
            gc.collect()

        # 更新有效性标志
        if not all(np.isnan(sr_h8sr)):
            valid_flag = 1
            record['valid_flag'] = valid_flag

    except Exception as e:
        error_msg = f"Processing failed: {str(e)}"
        print(f"[{timestamp()}] [ERROR] {error_msg}")
        traceback.print_exc()
        record['error'] = error_msg

    return (result_idx, gen_avail, sr_h8sr, valid_flag, record)


def process_hour(date, hour, stations, station_coords):
    """处理单小时数据"""
    date_str = date.strftime("%Y%m%d")
    hour_str = f"{hour * 100:04d}"
    time_key = f"{date_str}_{hour_str}"

    # 文件路径
    paths = {
        "sozSR": os.path.join(PATHS["hourly_sozSR"], date_str[:4], date_str[4:6],
                              f"H8_hourly_sozSR_angles_{time_key}.nc"),
        "merra_slv": os.path.join(PATHS["merra2_slv"], date_str[:4], date_str[4:6], f"MERRA2_{time_key}_TO3_TQV.nc"),
        "merra_aer": os.path.join(PATHS["merra2_aer"], date_str[:4], date_str[4:6], f"MERRA2_{time_key}_AOT550.nc"),
        "output_h8sr": os.path.join(PATHS["output_h8sr"], f"H8SR_{time_key}.nc")  # 只保留H8SR输出
    }
    os.makedirs(PATHS["output_parquet"], exist_ok=True)
    parquet_path = os.path.join(PATHS["output_parquet"], f"Correction_Records_{time_key}.parquet")

    # 检查输出文件
    if os.path.exists(paths["output_h8sr"]):
        print(f"[{timestamp()}] [SKIPPED] Output exists: {paths['output_h8sr']}")
        return paths["output_h8sr"], (0, 0, 0.0)

    # 检查输入文件
    missing_files = [p for p in [paths["sozSR"], paths["merra_slv"], paths["merra_aer"]] if not os.path.exists(p)]
    if missing_files:
        print(f"[{timestamp()}] [SKIPPED] Missing files: {', '.join(missing_files)}")
        return None, (0, 0, 0.0)

    # 加载数据
    print(f"[{timestamp()}] [INFO] Loading data for {time_key}")
    hourly = load_netcdf(paths["sozSR"], ['Station'] + BAND_NAMES + ANGLE_NAMES + ['hourly_availability'])
    merra2_slv = load_netcdf(paths["merra_slv"], ['Station', 'TO3', 'TQV'])
    merra2_aer = load_netcdf(paths["merra_aer"], ['Station', 'AOT550'])
    brdf_data = load_daily_brdf_data(date)

    if None in [hourly, merra2_slv, merra2_aer]:
        print(f"[{timestamp()}] [ERROR] Data load failed")
        return None, (0, 0, 0.0)

    # 检查站点匹配
    hourly_stations = hourly.get('Station', [])
    station_idx = {s: i for i, s in enumerate(hourly_stations)}
    matched = [s for s in stations if s in station_idx]

    if not matched:
        print(f"[{timestamp()}] [WARNING] No stations matched")
        return None, (0, 0, 0.0)

    # 准备结果数组
    station_map = {s: i for i, s in enumerate(stations)}
    num_stations = len(stations)

    # 准备收集详细记录的列表
    records_list = []

    # 创建共享内存用于结果存储
    sr_h8sr_shm = None
    flags_shm = None

    try:
        # H8SR结果共享内存
        sr_h8sr_shape = (num_stations, len(BAND_WAVELENGTHS))
        sr_h8sr_shm = shared_memory.SharedMemory(create=True, size=int(np.prod(sr_h8sr_shape) * np.float32().itemsize))
        sr_h8sr_array = np.ndarray(sr_h8sr_shape, dtype=np.float32, buffer=sr_h8sr_shm.buf)
        sr_h8sr_array[:] = np.nan

        # 标志共享内存
        flags_shape = (num_stations, 2)  # [gen_avail, valid_flag]
        flags_shm = shared_memory.SharedMemory(create=True, size=int(np.prod(flags_shape) * np.int8().itemsize))
        flags_array = np.ndarray(flags_shape, dtype=np.int8, buffer=flags_shm.buf)
        flags_array[:] = -1  # 初始化为-1

        # 准备任务
        tasks = []
        for station in matched:
            idx = station_idx[station]
            sidx = station_map[station]
            tasks.append((
                station, idx, hourly, merra2_slv, merra2_aer,
                station_coords, date, hour, sidx,
                brdf_data.get(station, {})
            ))

        # 并行处理
        start_time = time.time()
        valid_count = 0
        total_matched = len(matched)

        # 资源使用控制
        physical_cores = os.cpu_count() // 2 if os.cpu_count() > 4 else os.cpu_count()
        max_workers = min(physical_cores, 12)

        print(f"[{timestamp()}] [INFO] Processing {len(tasks)} stations with {max_workers} workers")

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_station_worker, task): task for task in tasks}

            for future in as_completed(futures):
                try:
                    result_idx, gen_avail, sr_h8sr, valid_flag, record = future.result()

                    # 更新共享内存
                    sr_h8sr_array[result_idx] = sr_h8sr
                    flags_array[result_idx, 0] = gen_avail
                    flags_array[result_idx, 1] = valid_flag

                    # 收集记录
                    records_list.append(record)

                    if valid_flag == 1:
                        valid_count += 1
                except Exception as e:
                    print(f"[{timestamp()}] [ERROR] Task failed: {str(e)}")
                    traceback.print_exc()

        # 复制结果到本地内存
        sr_h8sr_local = sr_h8sr_array.copy()
        gen_avail_local = flags_array[:, 0].copy()
        valid_flags_local = flags_array[:, 1].copy()

        # 保存Parquet记录
        if records_list:
            try:
                # 转换为DataFrame并保存
                df = pd.DataFrame(records_list)
                df.to_parquet(parquet_path, index=False)
                print(f"[{timestamp()}] [INFO] Saved Parquet records: {parquet_path}")
            except Exception as e:
                print(f"[{timestamp()}] [ERROR] Failed to save Parquet: {str(e)}")
        else:
            print(f"[{timestamp()}] [WARNING] No records to save for {time_key}")

        # 保存结果到文件
        try:
            # 创建输出目录
            os.makedirs(os.path.dirname(paths["output_h8sr"]), exist_ok=True)

            # 保存H8SR结果
            with nc.Dataset(paths["output_h8sr"], 'w') as ds:
                ds.createDimension('station', num_stations)

                # 站点变量
                station_var = ds.createVariable('Station', str, ('station',))
                station_var[:] = np.array(stations, dtype=object)

                # 可用性变量
                gen_var = ds.createVariable('General_availability', 'i1', ('station',))
                gen_var[:] = gen_avail_local

                # 有效性标志
                valid_var = ds.createVariable('valid_flag', 'i1', ('station',))
                valid_var[:] = valid_flags_local

                # 波段数据
                for i, band in enumerate(BAND_NAMES):
                    band_var = ds.createVariable(band, 'f4', ('station',))
                    band_var[:] = sr_h8sr_local[:, i]
                    band_var.units = "reflectance"

                # 元数据
                ds.date_created = timestamp()
                ds.title = f'Himawari-8 Surface Reflectance (BRDF Corrected) - {time_key}'
                ds.time = hour_str
                ds.date = date_str
                ds.source = "6S atmospheric correction with MODIS BRDF"

            ratio = valid_count / total_matched if total_matched > 0 else 0
            elapsed = time.time() - start_time
            print(
                f"[{timestamp()}] [SUCCESS] Saved output for {time_key} - Valid: {valid_count}/{total_matched} ({ratio:.1%}) in {elapsed:.1f}s")
            return paths["output_h8sr"], (valid_count, total_matched, ratio)
        except Exception as e:
            print(f"[{timestamp()}] [ERROR] Save failed: {str(e)}")
            return None, (0, 0, 0.0)

    finally:
        # 清理共享内存
        if sr_h8sr_shm:
            sr_h8sr_shm.close()
            sr_h8sr_shm.unlink()
        if flags_shm:
            flags_shm.close()
            flags_shm.unlink()


def load_coords():
    """加载站点坐标"""
    try:
        with nc.Dataset(PATHS["luts"]) as ds:
            stations = [str(s).strip() for s in ds.variables['Station'][:]]
            lats = ds.variables['Lat'][:]
            lons = ds.variables['Lon'][:]

            if isinstance(lats, np.ma.MaskedArray):
                lats = lats.filled(np.nan)
            if isinstance(lons, np.ma.MaskedArray):
                lons = lons.filled(np.nan)

            coords = {s: (lat, lon) for s, lat, lon in zip(stations, lats, lons)}
            print(f"[{timestamp()}] [INFO] Loaded coordinates for {len(coords)} stations")
            return coords
    except Exception as e:
        print(f"[{timestamp()}] [ERROR] Coords load failed: {str(e)}")
        return {}


def main():
    """主处理函数"""
    start = time.time()
    print(f"[{timestamp()}] [START] Processing from {START_DATE} to {END_DATE}")

    # 准备目录
    os.makedirs(PATHS["output_h8sr"], exist_ok=True)
    os.makedirs(PATHS["output_parquet"], exist_ok=True)

    # 加载基础数据
    print(f"[{timestamp()}] [INFO] Loading station data...")
    station_coords = load_coords()
    if not station_coords:
        print(f"[{timestamp()}] [ERROR] No station coordinates")
        return

    stations = list(station_coords.keys())
    print(f"[{timestamp()}] [INFO] Loaded {len(stations)} stations")

    # 生成日期列表
    dates = []
    current = START_DATE
    while current <= END_DATE:
        dates.append(current)
        current += timedelta(days=1)

    # 准备任务
    tasks = []
    for date in dates:
        for hour in PROCESS_HOURS:
            tasks.append((date, hour, stations, station_coords))

    print(f"[{timestamp()}] [INFO] Total tasks: {len(tasks)}")

    # 处理任务
    processed_h8sr = []
    total_valid = 0
    total_stations = 0

    for task in tasks:
        date, hour, *_ = task
        time_key = f"{date.strftime('%Y%m%d')}_{hour * 100:04d}"
        print(f"[{timestamp()}] [PROCESSING] {time_key}")

        output, stats = process_hour(*task)
        if output:
            processed_h8sr.append(output)
            v, t, _ = stats
            total_valid += v
            total_stations += t

    # 最终统计
    hours = (time.time() - start) / 3600
    ratio = total_valid / total_stations if total_stations else 0

    print(f"\n[{timestamp()}] [SUMMARY] Processing completed")
    print(f"  Processed H8SR files: {len(processed_h8sr)}")
    print(f"  Total stations processed: {total_stations}")
    print(f"  Valid stations: {total_valid} ({ratio:.1%})")
    print(f"  Total time: {hours:.2f} hours")


if __name__ == "__main__":
    multiprocessing.set_start_method('spawn', force=True)
    main()