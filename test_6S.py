import os
import netCDF4 as nc
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# 配置路径（与主代码一致）
PATHS = {
    "hourly_toa": "D:/H8_data/Hourly_TOA_Angles/",
    "merra2": "D:/H8_data/MERRA2_slv/",
    "merra2_aot550": "D:/H8_data/MERRA2_aer/",
    "lucc": "D:/H8_data/LC_2015_2024.nc",
    "output": "D:/H8_Data/H8SR/",
    "luts": "D:/H8_data/LUTs.nc",
}


def load_lucc_data():
    """加载土地覆盖数据"""
    with nc.Dataset(PATHS["lucc"]) as ds:
        stations = [str(s).strip() for s in ds['Station'][:]]
        lucc = ds['LC_type1'][0, :].filled(255)
        return dict(zip(stations, lucc))


def load_station_coords():
    """加载站点坐标"""
    with nc.Dataset(PATHS["luts"]) as ds:
        stations = [str(s).strip() for s in ds['Station'][:]]
        lats = ds['Lat'][:].filled(np.nan)
        lons = ds['Lon'][:].filled(np.nan)
        return {s: (lat, lon) for s, lat, lon in zip(stations, lats, lons)}


def analyze_input_data(date, hour):
    """分析输入数据质量"""
    date_str = date.strftime("%Y%m%d")
    hour_str = f"{hour * 100:04d}"
    time_key = f"{date_str}_{hour_str}"

    # 创建分析结果容器
    analysis = {
        'date': date,
        'hour': hour,
        'toa_stats': {},
        'merra_stats': {},
        'aot_stats': {},
        'problems': []
    }

    # 分析TOA数据
    toa_path = os.path.join(PATHS["hourly_toa"], date_str[:4], date_str[4:6],
                            f"H8_hourly_TOA_angles_{time_key}.nc")
    if os.path.exists(toa_path):
        try:
            with nc.Dataset(toa_path) as ds:
                for band in ['Albedo_03', 'Albedo_04']:
                    if band in ds.variables:
                        data = ds[band][:].filled(np.nan)
                        valid = data[(data >= 0) & (data <= 1)]
                        analysis['toa_stats'][band] = {
                            'mean': np.nanmean(valid) if len(valid) > 0 else np.nan,
                            'max': np.nanmax(data),
                            'min': np.nanmin(data),
                            'nan_count': np.isnan(data).sum(),
                            'out_of_range': ((data < 0) | (data > 1)).sum(),
                            'soz_values': ds['SOZ'][:].filled(np.nan) if 'SOZ' in ds.variables else np.array([])
                        }
                # 添加太阳天顶角分析
                if 'SOZ' in ds.variables:
                    soz = ds['SOZ'][:].filled(np.nan)
                    analysis['soz_stats'] = {
                        'mean': np.nanmean(soz),
                        'max': np.nanmax(soz),
                        'min': np.nanmin(soz),
                        'high_count': (soz > 75).sum(),
                        'nan_count': np.isnan(soz).sum()
                    }
        except Exception as e:
            analysis['problems'].append(f"TOA file error: {str(e)}")
    else:
        analysis['problems'].append("TOA file not found")

    # 分析MERRA2数据
    merra_path = os.path.join(PATHS["merra2"], date_str[:4], date_str[4:6],
                              f"MERRA2_{time_key}_TO3_TQV.nc")
    if os.path.exists(merra_path):
        try:
            with nc.Dataset(merra_path) as ds:
                for var in ['TO3', 'TQV']:
                    if var in ds.variables:
                        data = ds[var][:].filled(np.nan)
                        analysis['merra_stats'][var] = {
                            'mean': np.nanmean(data),
                            'max': np.nanmax(data),
                            'min': np.nanmin(data),
                            'nan_count': np.isnan(data).sum()
                        }
        except Exception as e:
            analysis['problems'].append(f"MERRA2 file error: {str(e)}")
    else:
        analysis['problems'].append("MERRA2 file not found")

    # 分析AOT数据
    aot_path = os.path.join(PATHS["merra2_aot550"], date_str[:4], date_str[4:6],
                            f"MERRA2_{time_key}_AOT550.nc")
    if os.path.exists(aot_path):
        try:
            with nc.Dataset(aot_path) as ds:
                if 'AOT550' in ds.variables:
                    aot = ds['AOT550'][:].filled(np.nan)
                    analysis['aot_stats'] = {
                        'mean': np.nanmean(aot),
                        'max': np.nanmax(aot),
                        'min': np.nanmin(aot),
                        'nan_count': np.isnan(aot).sum(),
                        'negative': (aot < 0).sum(),
                        'high': (aot > 1).sum()
                    }
        except Exception as e:
            analysis['problems'].append(f"AOT file error: {str(e)}")
    else:
        analysis['problems'].append("AOT file not found")

    return analysis


def analyze_output_data(date, hour):
    """分析输出数据质量"""
    date_str = date.strftime("%Y%m%d")
    hour_str = f"{hour * 100:04d}"
    sr_path = os.path.join(PATHS["output"], f"SR_{date_str}_{hour_str}.nc")

    analysis = {'exists': False, 'problems': []}
    if os.path.exists(sr_path):
        try:
            analysis['exists'] = True
            with nc.Dataset(sr_path) as ds:
                for band in ['Albedo_03', 'Albedo_04']:
                    if band in ds.variables:
                        data = ds[band][:].filled(np.nan)
                        valid = data[(data >= 0) & (data <= 1)]
                        invalid = data[(data < 0) | (data > 1)]

                        analysis[band] = {
                            'mean': np.nanmean(valid) if len(valid) > 0 else np.nan,
                            'max': np.nanmax(data),
                            'min': np.nanmin(data),
                            'nan_count': np.isnan(data).sum(),
                            'valid_count': len(valid),
                            'invalid_count': len(invalid),
                            'high_value_ratio': (data > 1).sum() / len(data) if len(data) > 0 else 0,
                            'low_value_ratio': (data < 0).sum() / len(data) if len(data) > 0 else 0
                        }

                # 添加有效性标志分析
                if 'valid_flag' in ds.variables:
                    flags = ds['valid_flag'][:].filled(-1)
                    analysis['flag_stats'] = {
                        'valid_count': (flags == 1).sum(),
                        'invalid_count': (flags == 0).sum(),
                        'unknown_count': (flags == -1).sum()
                    }
        except Exception as e:
            analysis['problems'].append(f"SR file error: {str(e)}")
    else:
        analysis['problems'].append("SR file not found")

    return analysis


def correlate_problems(input_analysis, output_analysis):
    """关联输入和输出问题"""
    problems = []

    # 检查太阳天顶角问题
    soz_stats = input_analysis.get('soz_stats', {})
    if soz_stats.get('high_count', 0) > 0:
        problems.append(f"High SOZ count: {soz_stats['high_count']} stations with SOZ > 75°")

    # 检查TOA反射率异常
    for band in ['Albedo_03', 'Albedo_04']:
        toa_stats = input_analysis['toa_stats'].get(band, {})
        sr_stats = output_analysis.get(band, {})

        if 'out_of_range' in toa_stats and toa_stats['out_of_range'] > 0:
            problems.append(f"TOA {band} has {toa_stats['out_of_range']} out-of-range values")

        if 'high_value_ratio' in sr_stats and sr_stats['high_value_ratio'] > 0.1:
            problems.append(
                f"High SR in {band}: {sr_stats['high_value_ratio'] * 100:.1f}% >1, "
                f"max={sr_stats.get('max', 0):.2f}"
            )

    # 检查AOT异常
    aot_stats = input_analysis.get('aot_stats', {})
    if aot_stats.get('negative', 0) > 0:
        problems.append(f"AOT has {aot_stats['negative']} negative values")
    if aot_stats.get('high', 0) > 0:
        problems.append(f"AOT has {aot_stats['high']} values >1")

    # 检查MERRA2数据缺失
    for var in ['TO3', 'TQV']:
        merra_stats = input_analysis['merra_stats'].get(var, {})
        if merra_stats.get('nan_count', 0) > 0:
            problems.append(f"MERRA2 {var} has {merra_stats['nan_count']} NaN values")

    return problems


def visualize_data_quality(analysis):
    """可视化数据质量问题"""
    if not analysis['input'] or not analysis['output']:
        return

    date_str = analysis['date'].strftime("%Y%m%d")
    hour = analysis['hour']

    try:
        fig, axs = plt.subplots(2, 2, figsize=(15, 10))
        fig.suptitle(f"Data Quality: {date_str} {hour:02d}:00", fontsize=16)

        # TOA反射率分布
        for band in ['Albedo_03', 'Albedo_04']:
            if band in analysis['input']['toa_stats']:
                data = analysis['input']['toa_stats'][band]
                axs[0, 0].hist(data['values'], bins=50, alpha=0.5, label=band) if 'values' in data else None
        axs[0, 0].set_title('TOA Reflectance Distribution')
        axs[0, 0].legend()

        # AOT分布
        if 'values' in analysis['input'].get('aot_stats', {}):
            axs[0, 1].hist(analysis['input']['aot_stats']['values'], bins=50)
            axs[0, 1].set_title('AOT550 Distribution')

        # SR反射率分布
        for band in ['Albedo_03', 'Albedo_04']:
            if band in analysis['output'] and 'values' in analysis['output'][band]:
                axs[1, 0].hist(analysis['output'][band]['values'], bins=50, alpha=0.5, label=band)
        axs[1, 0].set_title('Surface Reflectance Distribution')
        axs[1, 0].axvline(x=1, color='r', linestyle='--', label='Max Valid')
        axs[1, 0].legend()

        # 问题统计
        if analysis['problems']:
            problem_types = [p.split(':')[0] for p in analysis['problems']]
            pd.Series(problem_types).value_counts().plot(kind='bar', ax=axs[1, 1])
            axs[1, 1].set_title('Data Quality Issues')

        plt.tight_layout(rect=[0, 0, 1, 0.96])
        plt.savefig(f"data_quality_{date_str}_{hour}.png")
        plt.close()
    except Exception as e:
        print(f"Visualization error for {date_str} {hour}: {str(e)}")


def full_data_diagnostic(start_date, end_date, sample_size=10):
    """完整数据诊断流程"""
    # 生成日期范围（使用Python datetime）
    dates = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]

    # 随机采样日期
    if len(dates) > sample_size:
        sampled_dates = np.random.choice(dates, size=sample_size, replace=False)
    else:
        sampled_dates = dates

    results = []

    for date in sampled_dates:
        # 只处理主代码中的小时范围
        for hour in [0, 6, 11, 21, 22]:  # 覆盖主代码中的小时范围
            date_str = date.strftime("%Y%m%d")
            print(f"Analyzing {date_str} {hour:02d}:00")

            analysis = {
                'date': date,
                'hour': hour,
                'input': analyze_input_data(date, hour),
                'output': analyze_output_data(date, hour),
                'problems': []
            }

            if analysis['input'] and analysis['output'] and analysis['output']['exists']:
                analysis['problems'] = correlate_problems(analysis['input'], analysis['output'])

            results.append(analysis)
            visualize_data_quality(analysis)

    # 生成总结报告
    report_path = "data_quality_report.txt"
    with open(report_path, "w") as f:
        f.write("Himawari-8 6S+BRDF 数据质量诊断报告\n")
        f.write(f"分析时段: {start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}\n")
        f.write(f"分析样本: {len(results)} 个时间点\n\n")

        # 汇总统计
        high_sr_count = 0
        problem_types = {}
        high_soz_count = 0

        for res in results:
            for band in ['Albedo_03', 'Albedo_04']:
                if band in res['output']:
                    sr_stats = res['output'][band]
                    if sr_stats.get('high_value_ratio', 0) > 0:
                        high_sr_count += 1

            if 'soz_stats' in res['input'] and res['input']['soz_stats'].get('high_count', 0) > 0:
                high_soz_count += 1

            for problem in res['problems']:
                p_type = problem.split(':')[0]
                problem_types[p_type] = problem_types.get(p_type, 0) + 1

        f.write(f"发现SR>1的文件: {high_sr_count}/{len(results)} ({high_sr_count / len(results):.1%})\n")
        f.write(f"高太阳天顶角(>75°)的文件: {high_soz_count}/{len(results)}\n")

        f.write("\n主要问题分布:\n")
        for p_type, count in problem_types.items():
            f.write(f"- {p_type}: {count} 次出现\n")

        f.write("\n建议修复措施:\n")
        if high_soz_count > 0:
            f.write("1. 添加太阳天顶角阈值检查 (SOZ > 75° 时跳过处理)\n")
        if high_sr_count > 0:
            f.write("2. 在TOA反射率计算中添加范围限制 (0-1)\n")
            f.write("3. 在SR结果保存前添加范围限制 (0-1)\n")
        if any("AOT" in p for p in problem_types):
            f.write("4. 加强AOT异常值处理 (负值或>1的值)\n")

    print(f"诊断报告已保存至: {report_path}")
    return results


if __name__ == "__main__":
    # 示例：分析2016年1月数据
    lucc_data = load_lucc_data()
    coords_data = load_station_coords()

    # 使用Python datetime对象
    start_date = datetime(2015, 7, 7)
    end_date = datetime(2015, 7, 10)

    full_data_diagnostic(
        start_date=start_date,
        end_date=end_date,
        sample_size=10
    )