import os
import xarray as xr
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from statsmodels.tsa.seasonal import MSTL
from pathlib import Path
import logging
import glob
import matplotlib.dates as mdates
from matplotlib import font_manager as fm

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
INPUT_DIR = r"D:\H8_data\NDVI_TimeSeries"  # 修改为包含站点文件的目录
OUTPUT_DIR = r"D:\H8_data\NDVI_Decomposition"

# 时间频率参数 (每小时频率)
OBS_PER_DAY = 24  # 每小时数据，每天24个观测点
DAYS_PER_YEAR = 365
YEARLY_PERIOD = OBS_PER_DAY * DAYS_PER_YEAR  # 年周期为 8760


def prepare_station_data(ndvi_series, status_series, time_index):
    """准备站点数据：重采样为小时频率并处理缺失值"""
    # 将时间索引转换为pandas DatetimeIndex
    time_index = pd.to_datetime(time_index)

    # 使用转换后的时间索引创建pandas Series
    ts = pd.Series(ndvi_series, index=time_index)
    status_ts = pd.Series(status_series, index=time_index)

    # 定义开始和结束时间（替换为整点）
    start_time = pd.to_datetime(time_index[0]).replace(hour=0, minute=0, second=0)
    end_time = pd.to_datetime(time_index[-1]).replace(hour=23, minute=0, second=0)

    # 创建完整的小时时间索引
    full_time_index = pd.date_range(start=start_time, end=end_time, freq='h')

    # 重新索引并插值序列
    ts_full = ts.reindex(full_time_index)
    status_ts_full = status_ts.reindex(full_time_index, method='ffill')  # 前向填充状态值

    # 统一处理缺失值和夜间数据
    mask = (status_ts_full == -1) | ts_full.isnull()
    ts_full[mask] = np.nan

    # 应用7天窗口平滑（处理所有缺失值）
    logger.info("应用7天窗口平滑处理缺失值")
    ts_full = ts_full.interpolate(method='linear', limit_direction='both')
    ts_smoothed = ts_full.rolling(window='7D', min_periods=1, center=True).mean()
    ts_full[mask] = ts_smoothed[mask]

    # 应用365天窗口平滑（增强年周期平滑）
    logger.info("应用365天窗口年周期平滑")
    yearly_smoothed = ts_full.rolling(window='365D', min_periods=24, center=True).mean()
    ts_full = yearly_smoothed.combine_first(ts_full)

    # 最终平滑
    logger.info("应用5小时窗口整体平滑")
    ts_full = ts_full.rolling(window='5h', min_periods=1, center=True).mean()

    return ts_full, status_ts_full


def mstl_decomposition(ts):
    """执行MSTL分解，优化季节性参数"""
    # 确定周期参数
    periods = [OBS_PER_DAY]  # 日周期

    # 检查是否有足够数据支持年周期分解
    if len(ts) >= 2 * YEARLY_PERIOD:
        periods.append(YEARLY_PERIOD)
        logger.info(f"启用年周期分解 (周期={YEARLY_PERIOD})")
    else:
        logger.info(f"数据不足2个年周期，禁用年周期分解")

    # MSTL参数配置（增强季节性平滑）
    mstl_kwargs = {
        'stl_kwargs': {
            'seasonal_deg': 0,  # 常数季节性（更平滑）
            'robust': True,  # 使用鲁棒拟合
            'seasonal_jump': 24,  # 季节性平滑跳跃
            'trend_jump': 24 * 7,  # 趋势平滑跳跃
        }
    }

    # 执行MSTL分解
    if periods:
        result = MSTL(ts, periods=periods, **mstl_kwargs).fit()

        # 初始化分量
        components = {
            'trend': result.trend,
            'resid': result.resid,
            'yearly': pd.Series(0, index=ts.index),
            'diurnal': pd.Series(0, index=ts.index)
        }

        # 处理分量
        if isinstance(result.seasonal, pd.DataFrame):
            for comp_name in result.seasonal.columns:
                if 'seasonal' in comp_name:
                    if str(OBS_PER_DAY) in comp_name:
                        components['diurnal'] = result.seasonal[comp_name]
                    elif str(YEARLY_PERIOD) in comp_name:
                        components['yearly'] = result.seasonal[comp_name]
        else:
            components['diurnal'] = result.seasonal

        return components
    else:
        # 简单趋势分解作为后备
        logger.warning("数据不足，使用简单趋势分解")
        trend = ts.rolling(window='24H', min_periods=1, center=True).mean()
        resid = ts - trend
        return {
            'trend': trend,
            'yearly': pd.Series(0, index=ts.index),
            'diurnal': pd.Series(0, index=ts.index),
            'resid': resid
        }


def plot_components(station_id, ts, status_ts, components, output_dir):
    """绘制分解分量和附加图表（科研优化版）"""
    # 创建输出目录
    station_output_dir = output_dir / station_id
    station_output_dir.mkdir(parents=True, exist_ok=True)

    # 检查图表是否已存在
    plot_files = [
        station_output_dir / f"{station_id}_decomposition.png",
        station_output_dir / f"{station_id}_yearly_component.png",
        station_output_dir / f"{station_id}_diurnal_component.png"
    ]

    if all(f.exists() for f in plot_files):
        logger.info(f"站点 {station_id} 的图表已存在，跳过绘制")
        return

    # 1. 创建主分解图（6个子图）- 科研风格
    fig, axs = plt.subplots(6, 1, figsize=(10, 18), dpi=300)
    fig.suptitle(f'NDVI Decomposition - Station {station_id}',
                 fontsize=16, fontname='Times New Roman', y=0.95)

    # 计算原始NDVI（各分量之和）
    original = components['trend'] + components['yearly'] + components['diurnal'] + components['resid']

    # 绘制各分量
    titles = ['Original NDVI', 'Trend', 'Yearly Component',
              'Diurnal Component', 'Residual', 'Residual/Original']
    data_series = [original, components['trend'], components['yearly'], components['diurnal'],
                   components['resid'], components['resid'] / original]

    for i, (title, data) in enumerate(zip(titles, data_series)):
        ax = axs[i]
        ax.plot(data.index, data, 'b-', linewidth=0.8, color='#1f77b4')
        ax.set_title(title, fontname='Times New Roman', fontsize=12)
        ax.tick_params(axis='both', which='major', labelsize=9)
        ax.set_xlim(data.index[0], data.index[-1])

        # 移除网格和边框装饰
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

    # 2. 创建平均年分量图 - 科研风格
    fig2, ax2 = plt.subplots(figsize=(8, 4), dpi=300)

    if not components['yearly'].empty:
        yearly_df = pd.DataFrame({'yearly': components['yearly']})
        yearly_df['day_of_year'] = yearly_df.index.dayofyear
        avg_yearly = yearly_df.groupby('day_of_year')['yearly'].mean()

        ax2.plot(avg_yearly.index, avg_yearly, '-', linewidth=1.5, color='#d62728')
        ax2.set_title(f'Average Yearly Component - Station {station_id}',
                      fontname='Times New Roman', fontsize=12)
        ax2.set_xlabel('Day of Year', fontname='Times New Roman')
        ax2.set_ylabel('Yearly Component', fontname='Times New Roman')
        ax2.tick_params(axis='both', labelsize=9)
        ax2.set_xlim(0, 365)

        # 科研风格优化
        ax2.spines['top'].set_visible(False)
        ax2.spines['right'].set_visible(False)
        ax2.spines['bottom'].set_linewidth(0.5)
        ax2.spines['left'].set_linewidth(0.5)

    else:
        ax2.text(0.5, 0.5, 'No yearly component available',
                 horizontalalignment='center', fontsize=12, fontname='Times New Roman')

    plt.tight_layout()

    # 3. 创建平均日分量图（UTC+8）- 科研风格
    fig3, ax3 = plt.subplots(figsize=(8, 4), dpi=300)

    if not components['diurnal'].empty:
        # 转换为UTC+8（北京时间）
        diurnal_df = pd.DataFrame({
            'diurnal': components['diurnal'],
            'status': status_ts
        })
        diurnal_df.index = diurnal_df.index + pd.Timedelta(hours=8)  # UTC+8转换
        diurnal_df['hour'] = diurnal_df.index.hour

        # 按小时分组计算统计量
        grouped = diurnal_df.groupby('hour')
        avg_diurnal = grouped['diurnal'].mean()
        std_diurnal = grouped['diurnal'].std()

        # 计算每个小时的数据可用性
        def calculate_availability(group):
            total = len(group)
            day_count = sum(group['status'].isin([0, 1]))
            return day_count / total if total > 0 else 0

        availability = grouped.apply(calculate_availability)

        # 准备颜色映射
        colors = []
        for hour in sorted(diurnal_df['hour'].unique()):
            if availability[hour] >= 0.25:
                colors.append('#1f77b4')  # 蓝色：足够白天数据
            elif availability[hour] <= 0.25:  # 即夜晚数据≥75%
                colors.append('#ff7f0e')  # 橙色：主要夜间数据

        # 绘制带误差线的折线图
        hours = sorted(diurnal_df['hour'].unique())
        ax3.plot(hours, avg_diurnal, '-', linewidth=1.5, color='#2c7bb6')
        ax3.fill_between(hours,
                         avg_diurnal - std_diurnal,
                         avg_diurnal + std_diurnal,
                         color='#abd9e9', alpha=0.3)

        # 标记数据可用性
        for i, hour in enumerate(hours):
            ax3.plot(hour, avg_diurnal[hour], 'o',
                     markersize=6, color=colors[i],
                     markeredgecolor='w', markeredgewidth=0.5)

        ax3.set_title(f'Diurnal Component (Beijing Time UTC+8) - Station {station_id}',
                      fontname='Times New Roman', fontsize=12)
        ax3.set_xlabel('Hour of Day (UTC+8)', fontname='Times New Roman')
        ax3.set_ylabel('Diurnal Component', fontname='Times New Roman')
        ax3.set_xticks(range(0, 24, 2))
        ax3.tick_params(axis='both', labelsize=9)
        ax3.set_xlim(-0.5, 23.5)

        # 添加图例
        from matplotlib.lines import Line2D
        legend_elements = [
            Line2D([0], [0], marker='o', color='w', markerfacecolor='#1f77b4',
                   markersize=8, label='≥25% Daytime Data'),
            Line2D([0], [0], marker='o', color='w', markerfacecolor='#ff7f0e',
                   markersize=8, label='≥75% Night Data')
        ]
        ax3.legend(handles=legend_elements, loc='best', frameon=False, fontsize=9)

        # 科研风格优化
        ax3.spines['top'].set_visible(False)
        ax3.spines['right'].set_visible(False)
        ax3.spines['bottom'].set_linewidth(0.5)
        ax3.spines['left'].set_linewidth(0.5)

    else:
        ax3.text(0.5, 0.5, 'No diurnal component available',
                 horizontalalignment='center', fontsize=12, fontname='Times New Roman')

    plt.tight_layout()

    # 保存图表
    fig.savefig(plot_files[0], dpi=300, bbox_inches='tight')
    fig2.savefig(plot_files[1], dpi=300, bbox_inches='tight')
    fig3.savefig(plot_files[2], dpi=300, bbox_inches='tight')

    plt.close('all')
    logger.info(f"站点 {station_id} 的分解图表已保存")


def process_station(station_file, output_dir):
    """处理单个站点的分解"""
    station_id = station_file.stem.split('_')[-1]

    # 加载站点数据
    try:
        with xr.open_dataset(station_file) as ds:
            time_index = ds['time'].values
            ndvi_series = ds['NDVI'].values
            status_series = ds['status'].values

        # 准备时间序列数据
        ts, status_ts = prepare_station_data(ndvi_series, status_series, time_index)

        # 执行MSTL分解
        components = mstl_decomposition(ts)

        # 绘制分量图表
        plot_components(station_id, ts, status_ts, components, output_dir)

        return True
    except Exception as e:
        logger.error(f"处理站点 {station_id} 时出错: {str(e)}")
        return False


def main():
    """主函数：处理每个站点的NDVI时间序列"""
    # 创建输出目录
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 获取所有站点文件
    station_files = list(Path(INPUT_DIR).glob("NDVI_Station_*.nc"))

    if not station_files:
        logger.error(f"在目录 {INPUT_DIR} 中未找到任何站点文件")
        return

    logger.info(f"找到 {len(station_files)} 个站点文件")

    # 处理每个站点
    processed = 0
    skipped = 0
    for station_file in station_files:
        station_id = station_file.stem.split('_')[-1]

        # 检查是否已处理
        station_output_dir = output_dir / station_id
        if station_output_dir.exists():
            plot_files = [
                station_output_dir / f"{station_id}_decomposition.png",
                station_output_dir / f"{station_id}_yearly_component.png",
                station_output_dir / f"{station_id}_diurnal_component.png"
            ]

            if all(f.exists() for f in plot_files):
                logger.info(f"站点 {station_id} 的分解结果已存在，跳过")
                skipped += 1
                continue

        logger.info(f"处理站点 {station_id} ({processed + skipped + 1}/{len(station_files)})")
        if process_station(station_file, output_dir):
            processed += 1

    logger.info(f"处理完成! 成功处理 {processed} 个站点, 跳过 {skipped} 个站点")


if __name__ == "__main__":
    main()