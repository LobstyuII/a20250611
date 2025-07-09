H8L2PAR 数据文件说明
====================

1. 文件命名规则
   - 单时次文件: PAR_YYYYMMDD_HHMM.nc
     示例: PAR_20150707_0000.nc
   - 月整合文件: PAR_monthly_YYYYMM.nc
     示例: PAR_monthly_201507.nc
   - 说明:
     * YYYY: 年份 (4位数字)
     * MM: 月份 (2位数字)
     * DD: 日期 (2位数字)
     * HH: 小时 (UTC时间，2位数字)
     * MM: 分钟 (2位数字)

2. 文件格式
   - 格式类型: NetCDF-4
   - 维度:
        Station: 站点维度 (2014个站点)
        time: 时间维度 (仅月整合文件)
   - 变量: 2个 (单时次文件) 或 3个 (月整合文件)
   - 文件大小:
        单时次文件: 约50-100 KB
        月整合文件: 约10-20 MB (取决于当月天数)

3. 数据内容
   | 变量名   | 描述                         | 单位        | 数据类型 | 维度         | 属性                  |
   |----------|------------------------------|-------------|----------|--------------|-----------------------|
   | Station  | 站点名称                     | 无          | 字符串   | Station      |                       |
   | PAR      | 光合有效辐射                 | umol/m²/s   | float32  | Station      | long_name, units     |
   | time     | 时间戳 (仅月整合文件)        | 秒 (UTC)    | float64  | time         | units, calendar       |

4. 数据处理说明
   - 数据转换:
        PAR实际值 = 原始值 × scale_factor + add_offset
        scale_factor = 0.10000000149011612
        add_offset = 0.0
   - 数据质量:
        * 有效值范围: 0-25000 (原始值), 0-2500 (实际值)
        * 缺失值: NaN (原始值为-32768)
   - 时间表示:
        * 单时次文件: 全局属性 time = "HH:MM" (UTC时间)
        * 月整合文件: time变量 (秒数, UTC时间)

5. 数据来源
   - 卫星: 日本气象厅向日葵8号(Himawari-8)
   - 产品: L2级光合有效辐射(PAR)产品
   - 分辨率: 0.05度 (约5公里)
   - 原始文件:
        /pub/himawari/L2/PAR/021/YYYYMM/DD/HH/
        H08_YYYYMMDD_HHMM_RFL021_FLDK.02401_02401.nc
   - 获取方式: 日本宇宙航空研究开发机构(JAXA) P-Tree FTP服务器

6. 使用注意事项
   - 数据包含2014个特定站点的PAR值
   - 单时次文件每10分钟生成一个 (00,10,20,30,40,50分)
   - 月度数据整合后存储在PAR_monthly_YYYYMM.nc中
   - 处理脚本自动记录缺失文件在H8L2PAR_vacant.csv中

----------------------------------------------------------------

H8L2PAR Data File Documentation
================================

1. File Naming Convention
   - Single-time file: PAR_YYYYMMDD_HHMM.nc
     Example: PAR_20150707_0000.nc
   - Monthly integrated file: PAR_monthly_YYYYMM.nc
     Example: PAR_monthly_201507.nc
   - Description:
     * YYYY: Year (4-digit)
     * MM: Month (2-digit)
     * DD: Day (2-digit)
     * HH: Hour (UTC, 2-digit)
     * MM: Minute (2-digit)

2. File Format
   - Format Type: NetCDF-4
   - Dimensions:
        Station: Station dimension (2014 stations)
        time: Time dimension (monthly files only)
   - Variables: 2 (single-time) or 3 (monthly)
   - File Size:
        Single-time: ~50-100 KB
        Monthly: ~10-20 MB (depends on days in month)

3. Data Content
   | Variable  | Description                  | Units       | Data Type | Dimension    | Attributes            |
   |-----------|------------------------------|-------------|-----------|--------------|-----------------------|
   | Station   | Station names                | None        | String    | Station      |                       |
   | PAR       | Photosynthetically active radiation | umol/m²/s | float32   | Station      | long_name, units     |
   | time      | Timestamp (monthly only)     | seconds (UTC)| float64  | time         | units, calendar       |

4. Data Processing Notes
   - Data Conversion:
        PAR_actual = raw_value × scale_factor + add_offset
        scale_factor = 0.10000000149011612
        add_offset = 0.0
   - Data Quality:
        * Valid Range: 0-25000 (raw), 0-2500 (actual)
        * Missing Value: NaN (raw value -32768)
   - Time Representation:
        * Single-time: Global attribute time = "HH:MM" (UTC)
        * Monthly: time variable (seconds since 1970-01-01)

5. Data Source
   - Satellite: JMA Himawari-8
   - Product: L2 Photosynthetically Active Radiation (PAR)
   - Resolution: 0.05 degrees (~5 km)
   - Original Files:
        /pub/himawari/L2/PAR/021/YYYYMM/DD/HH/
        H08_YYYYMMDD_HHMM_RFL021_FLDK.02401_02401.nc
   - Access: JAXA P-Tree FTP Server

6. Usage Notes
   - Contains PAR values for 2014 specific stations
   - Single-time files generated every 10 minutes (00,10,20,30,40,50)
   - Monthly data integrated in PAR_monthly_YYYYMM.nc
   - Missing files automatically recorded in H8L2PAR_vacant.csv
"""
