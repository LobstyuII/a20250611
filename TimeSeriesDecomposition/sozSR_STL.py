import os
import xarray as xr
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
import matplotlib.dates as mdates
from statsmodels.tsa.seasonal import STL
import dask
from dask.diagnostics import ProgressBar
import warnings

# 配置科研级字体
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.serif'] = ['Times New Roman']
plt.rcParams['mathtext.fontset'] = 'stix'
plt.rcParams['axes.edgecolor'] = 'black'
plt.rcParams['axes.linewidth'] = 1.0

# 配置日志
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# 配置路径
INPUT_DIR = r"D:\H8_data\NDVI_TimeSeries"
OUTPUT_DIR = r"D:\H8_data\NDVI_Decomposition"

# 忽略特定警告
warnings.filterwarnings("ignore", category=UserWarning, module='statsmodels')
warnings.filterwarnings("ignore", category=RuntimeWarning)


def prepare_station_data(ndvi_series, status_series, time_index):
    """准备站点数据：重采样为小时频率并处理缺失值"""
    time_index = pd.to_datetime(time_index)
    ts = pd.Series(ndvi_series, index=time_index)
    status_ts = pd.Series(status_series, index=time_index)

    # 创建完整时间索引
    start_time = time_index[0].replace(hour=0, minute=0, second=0)
    end_time = time_index[-1].replace(hour=23, minute=0, second=0)
    full_time_index = pd.date_range(start=start_time, end=end_time, freq='h')

    # 重新索引
    ts_full = ts.reindex(full_time_index)
    status_ts_full = status_ts.reindex(full_time_index, method='ffill')

    # 处理缺失值和夜间数据
    mask = (status_ts_full == -1) | ts_full.isnull()
    ts_full[mask] = np.nan

    # 线性插值填补小缺失值
    ts_full = ts_full.interpolate(method='linear', limit=3)

    # 使用前后值填充边缘缺失值
    ts_full = ts_full.fillna(method='ffill').fillna(method='bfill')

    return ts_full, status_ts_full


def stl_decomposition(ts, status_ts):
    """执行STL分解"""
    # 设置STL参数
    period = 365 * 24  # 年周期（小时）
    seasonal = 13  # 平滑使用的季节窗口大小
    trend_window = max(101, min(len(ts) // 20, 201))  # 自适应趋势窗口

    # 执行STL分解
    stl = STL(
        ts,
        period=period,
        seasonal=seasonal,
        trend=trend_window,
        robust=True,
        seasonal_deg=0,
        trend_deg=1,
        low_pass_deg=1
    )

    # 拟合模型
    try:
        result = stl.fit()
    except Exception as e:
        logger.error(f"STL分解失败: {str(e)}")
        return None

    # 提取分量
    trend = pd.Series(result.trend, index=ts.index)
    seasonal = pd.Series(result.seasonal, index=ts.index)
    residual = pd.Series(result.resid, index=ts.index)

    # 仅保留真实采集点的残差
    residual[status_ts != 0] = np.nan

    return {
        'trend': trend,
        'seasonal': seasonal,
        'residual': residual
    }


def plot_components(station_id, ts, status_ts, components, output_dir):
    """绘制STL分解分量（科研优化版）"""
    station_output_dir = output_dir / station_id
    station_output_dir.mkdir(parents=True, exist_ok=True)

    # 创建图形
    fig, axs = plt.subplots(4, 1, figsize=(12, 14), dpi=300)
    fig.suptitle(f'STL Decomposition - Station {station_id}',
                 fontsize=16, fontname='Times New Roman', y=0.95)

    titles = ['Original NDVI', 'Trend Component', 'Seasonal Component', 'Residual Component']
    data_series = [ts, components['trend'], components['seasonal'], components['residual']]

    for i, (title, data) in enumerate(zip(titles, data_series)):
        ax = axs[i]

        # 特殊处理残差分量
        if i == 3:
            # 只绘制真实采集点
            valid_mask = (status_ts == 0)
            ax.plot(data.index[valid_mask], data[valid_mask], '.',
                    markersize=2, color='#1f77b4', alpha=0.7)
            ax.axhline(0, color='gray', linestyle='--', alpha=0.5)
        else:
            ax.plot(data.index, data, linewidth=0.8, color='#1f77b4')

        ax.set_title(title, fontname='Times New Roman', fontsize=12)
        ax.tick_params(axis='both', which='major', labelsize=9)

        # 科研风格优化
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_linewidth(0.5)
        ax.spines['left'].set_linewidth(0.5)

        if i == len(axs) - 1:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            ax.tick_params(axis='x', rotation=45)

    # 在原始NDVI图上添加数据点标记
    valid_mask = (status_ts == 0)
    night_mask = (status_ts == -1)

    if valid_mask.any():
        axs[0].plot(ts.index[valid_mask], ts[valid_mask], '.',
                    markersize=2, color='#2ca02c', alpha=0.6, label='Valid Daytime')
    if night_mask.any():
        axs[0].plot(ts.index[night_mask], ts[night_mask], 'o',
                    markersize=2, color='#ff7f0e', alpha=0.6, label='Night Interpolated')
    if valid_mask.any() or night_mask.any():
        axs[0].legend(loc='best', frameon=False, fontsize=9)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(station_output_dir / f"{station_id}_STL_decomposition.png", dpi=300, bbox_inches='tight')
    plt.close(fig)
    logger.info(f"站点 {station_id} 的STL分解图已保存")


def save_stl_results(station_id, ts, status_ts, components, output_dir):
    """保存STL分解结果为NetCDF文件"""
    station_output_dir = output_dir / station_id
    station_output_dir.mkdir(parents=True, exist_ok=True)

    # 创建数据集
    ds = xr.Dataset(
        {
            'NDVI_original': ('time', ts.values),
            'NDVI_trend': ('time', components['trend'].values),
            'NDVI_seasonal': ('time', components['seasonal'].values),
            'NDVI_residual': ('time', components['residual'].values),
            'status': ('time', status_ts.values)
        },
        coords={'time': ts.index}
    )

    # 设置属性
    ds.NDVI_original.attrs = {'long_name': 'Original NDVI', 'units': 'dimensionless'}
    ds.NDVI_trend.attrs = {'long_name': 'STL Trend Component', 'units': 'dimensionless'}
    ds.NDVI_seasonal.attrs = {'long_name': 'STL Seasonal Component', 'units': 'dimensionless'}
    ds.NDVI_residual.attrs = {'long_name': 'STL Residual Component (only valid points)', 'units': 'dimensionless'}
    ds.status.attrs = {
        'long_name': 'Data availability status',
        'flag_values': [-1, 0, 1],
        'flag_meanings': 'night_or_missing daytime_available daytime_unavailable'
    }

    # 保存文件
    nc_file = station_output_dir / f"STL_decomposition_{station_id}.nc"
    encoding = {
        'NDVI_original': {'zlib': True, 'complevel': 5},
        'NDVI_trend': {'zlib': True, 'complevel': 5},
        'NDVI_seasonal': {'zlib': True, 'complevel': 5},
        'NDVI_residual': {'zlib': True, 'complevel': 5},
        'status': {'zlib': True, 'complevel': 5, 'dtype': 'int8'}
    }
    ds.to_netcdf(nc_file, encoding=encoding)
    logger.info(f"站点 {station_id} 的STL分解结果已保存为NetCDF")


def process_station(station_file, output_dir):
    """处理单个站点的STL分解"""
    station_id = station_file.stem.split('_')[-1]

    try:
        logger.info(f"开始处理站点 {station_id}")

        # 读取数据
        with xr.open_dataset(station_file) as ds:
            time_index = ds['time'].values
            ndvi_series = ds['NDVI'].values
            status_series = ds['status'].values

        # 准备时间序列数据
        ts, status_ts = prepare_station_data(ndvi_series, status_series, time_index)

        # 检查有效数据点
        valid_points = np.sum(status_ts == 0)
        if valid_points < 1000:
            logger.warning(f"站点 {station_id} 有效数据点不足 ({valid_points})，跳过分解")
            return False

        # 执行STL分解
        logger.info(f"站点 {station_id} 执行STL分解...")
        components = stl_decomposition(ts, status_ts)

        if components is None:
            logger.error(f"站点 {station_id} STL分解失败")
            return False

        # 保存结果和图表
        save_stl_results(station_id, ts, status_ts, components, output_dir)
        plot_components(station_id, ts, status_ts, components, output_dir)

        return True
    except Exception as e:
        logger.error(f"处理站点 {station_id} 时出错: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def main():
    """主函数：并行处理站点STL分解"""
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 获取所有站点文件
    station_files = list(Path(INPUT_DIR).glob("NDVI_Station_*.nc"))

    if not station_files:
        logger.error(f"在目录 {INPUT_DIR} 中未找到任何站点文件")
        return

    logger.info(f"找到 {len(station_files)} 个站点文件")

    # 并行处理
    max_workers = min(8, os.cpu_count() - 1)
    processed = 0
    skipped = 0
    futures = []

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        for station_file in station_files:
            station_id = station_file.stem.split('_')[-1]
            station_output_dir = output_dir / station_id

            # 检查是否已处理
            nc_file = station_output_dir / f"STL_decomposition_{station_id}.nc"
            if nc_file.exists():
                logger.info(f"站点 {station_id} 的STL分解结果已存在，跳过")
                skipped += 1
                continue

            # 提交任务
            future = executor.submit(process_station, station_file, output_dir)
            futures.append(future)

        # 处理结果
        for future in as_completed(futures):
            try:
                if future.result():
                    processed += 1
                    logger.info(f"站点处理成功")
                else:
                    logger.error(f"站点处理失败")
            except Exception as e:
                logger.error(f"站点处理出错: {str(e)}")

    logger.info(f"STL分解完成! 成功处理 {processed} 个站点, 跳过 {skipped} 个站点")


if __name__ == "__main__":
    main()