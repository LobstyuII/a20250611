import os
import glob
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
from tqdm import tqdm
import warnings

# 忽略警告
warnings.filterwarnings('ignore')

# 配置参数
OUTPUT_DIR = r"D:\H8_data\rain_ndvi_analysis"
TEMP_DATA_DIR = os.path.join(OUTPUT_DIR, "hourly_ndvi_data")  # 临时数据目录
PRE_RAIN_HOURS = 72  # 降雨前观察小时数
POST_RAIN_HOURS = 672  # 降雨后观察小时数 (28天)
INTENSITY_CLASSES = ["小雨", "中雨", "大雨", "暴雨", "大暴雨", "特大暴雨"]
COLORS = sns.color_palette("husl", 6)  # 为6个强度类别定义颜色

# 创建输出目录
os.makedirs(OUTPUT_DIR, exist_ok=True)


def combine_hourly_data():
    """合并所有小时数据文件"""
    print("合并小时数据文件...")
    all_files = glob.glob(os.path.join(TEMP_DATA_DIR, "ndvi_data_*.parquet"))

    if not all_files:
        print("警告: 未找到小时数据文件")
        return pd.DataFrame()

    # 使用列表推导式逐步读取文件
    frames = []
    for file in tqdm(all_files, desc="读取小时文件"):
        try:
            df = pd.read_parquet(file)
            frames.append(df)
        except Exception as e:
            print(f"读取 {file} 时出错: {str(e)}")

    if frames:
        combined = pd.concat(frames, ignore_index=True)
        return combined
    return pd.DataFrame()


def plot_rain_ndvi_analysis(ndvi_windows, duration_group):
    """绘制降雨对resNDVI影响的分析图"""
    print(f"绘制持续时间为{duration_group}的分析图...")

    # 筛选指定持续时间的降雨事件
    group_data = ndvi_windows[ndvi_windows['Duration_Group'] == duration_group]

    if group_data.empty:
        print(f"没有找到持续时间分组{duration_group}的数据")
        return

    # 创建时间轴 - 分为降雨前和降雨后
    time_points = np.arange(-PRE_RAIN_HOURS, POST_RAIN_HOURS + 1)

    # 准备存储结果
    intensity_results = {ic: {'mean': [], 'std': [], 'count': []} for ic in INTENSITY_CLASSES}

    # 计算每个时间点和强度类别的统计量
    for t in time_points:
        if t < 0:  # 降雨前
            time_data = group_data[np.isclose(group_data['Hours_After_Start'], t, atol=0.5)]
        else:  # 降雨后
            time_data = group_data[np.isclose(group_data['Hours_After_End'], t, atol=0.5)]

        # 排除降雨期间的数据点
        time_data = time_data[~time_data['During_Rain']]

        for ic in INTENSITY_CLASSES:
            ic_data = time_data[time_data['Intensity_Class'] == ic]['NDVI']

            # 过滤无效值
            valid_data = ic_data.dropna()

            if not valid_data.empty:
                intensity_results[ic]['mean'].append(valid_data.mean())
                intensity_results[ic]['std'].append(valid_data.std())
                intensity_results[ic]['count'].append(len(valid_data))
            else:
                intensity_results[ic]['mean'].append(np.nan)
                intensity_results[ic]['std'].append(np.nan)
                intensity_results[ic]['count'].append(0)

    # 创建图形
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 12), sharex=True,
                                   gridspec_kw={'height_ratios': [3, 1]})

    # 绘制折线图（带方差）
    for i, ic in enumerate(INTENSITY_CLASSES):
        # 降雨前部分
        pre_idx = time_points < 0
        pre_means = intensity_results[ic]['mean'][:PRE_RAIN_HOURS]
        pre_stds = intensity_results[ic]['std'][:PRE_RAIN_HOURS]

        ax1.plot(time_points[pre_idx], pre_means,
                 color=COLORS[i], label=ic, linewidth=2)

        # 仅在有数据时绘制标准差区域
        valid_pre = ~np.isnan(pre_means) & ~np.isnan(pre_stds)
        if np.any(valid_pre):
            ax1.fill_between(
                time_points[pre_idx][valid_pre],
                np.array(pre_means)[valid_pre] - np.array(pre_stds)[valid_pre],
                np.array(pre_means)[valid_pre] + np.array(pre_stds)[valid_pre],
                color=COLORS[i], alpha=0.2
            )

        # 降雨后部分
        post_idx = time_points > 0
        post_means = intensity_results[ic]['mean'][PRE_RAIN_HOURS + 1:]
        post_stds = intensity_results[ic]['std'][PRE_RAIN_HOURS + 1:]

        ax1.plot(time_points[post_idx], post_means,
                 color=COLORS[i], linewidth=2)

        # 仅在有数据时绘制标准差区域
        valid_post = ~np.isnan(post_means) & ~np.isnan(post_stds)
        if np.any(valid_post):
            ax1.fill_between(
                time_points[post_idx][valid_post],
                np.array(post_means)[valid_post] - np.array(post_stds)[valid_post],
                np.array(post_means)[valid_post] + np.array(post_stds)[valid_post],
                color=COLORS[i], alpha=0.2
            )

    # 设置折线图属性
    ax1.set_title(f'降雨对NDVI的影响 (持续时间分组: {duration_group})', fontsize=16)
    ax1.set_ylabel('NDVI', fontsize=12)
    ax1.grid(True, linestyle='--', alpha=0.7)
    ax1.axvspan(-0.5, 0.5, alpha=0.2, color='gray')  # 标记降雨期间
    ax1.legend(loc='upper right', fontsize=10)

    # 绘制柱状图（有效数据量）
    bottom = np.zeros(len(time_points))
    for i, ic in enumerate(INTENSITY_CLASSES):
        counts = intensity_results[ic]['count']
        ax2.bar(time_points, counts, bottom=bottom, color=COLORS[i], width=0.8)
        bottom += counts

    # 设置柱状图属性
    ax2.set_xlabel('相对于降雨事件的时间 (小时)', fontsize=12)
    ax2.set_ylabel('有效数据点', fontsize=12)
    ax2.grid(True, linestyle='--', alpha=0.7)
    ax2.axvspan(-0.5, 0.5, alpha=0.2, color='gray')  # 标记降雨期间

    # 设置x轴
    plt.xticks(np.arange(-PRE_RAIN_HOURS, POST_RAIN_HOURS + 1, 24), rotation=45)
    plt.xlim(-PRE_RAIN_HOURS, POST_RAIN_HOURS)

    # 添加垂直线标记降雨开始和结束
    ax1.axvline(x=0, color='r', linestyle='--', alpha=0.7)
    ax2.axvline(x=0, color='r', linestyle='--', alpha=0.7)

    # 添加时间标签
    ax1.text(-PRE_RAIN_HOURS / 2, ax1.get_ylim()[1] * 0.9, "降雨前",
             ha='center', fontsize=12, bbox=dict(facecolor='white', alpha=0.8))
    ax1.text(POST_RAIN_HOURS / 2, ax1.get_ylim()[1] * 0.9, "降雨后",
             ha='center', fontsize=12, bbox=dict(facecolor='white', alpha=0.8))

    # 调整布局
    plt.tight_layout()

    # 保存图像
    output_path = os.path.join(OUTPUT_DIR, f"rain_ndvi_analysis_duration_{duration_group}.png")
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"已保存图像: {output_path}")


def main():
    """主函数：执行数据分析与绘图"""
    # 合并所有小时数据文件
    ndvi_windows = combine_hourly_data()

    if ndvi_windows.empty:
        print("未找到匹配的NDVI数据")
        return

    # 保存最终数据集
    final_output = os.path.join(OUTPUT_DIR, "combined_ndvi_data.parquet")
    ndvi_windows.to_parquet(final_output)
    print(f"已保存合并数据集: {final_output}")

    # 按持续时间分组进行分析
    for duration_group in ['Q1', 'Q2', 'Q3', 'Q4']:
        plot_rain_ndvi_analysis(ndvi_windows, duration_group)

    print("分析完成！所有图表已保存到:", OUTPUT_DIR)


if __name__ == "__main__":
    main()