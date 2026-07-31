#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
劳动赔偿金计算器
用于计算经济补偿金、赔偿金、加班费等
"""

import sys
from datetime import datetime
from typing import Dict, Tuple, Optional


def calculate_work_years(start_date: str, end_date: str) -> Tuple[int, int]:
    """
    计算工作年限

    Args:
        start_date: 入职日期，格式 "YYYY-MM-DD"
        end_date: 离职日期，格式 "YYYY-MM-DD"

    Returns:
        (年数, 月数)
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    years = end.year - start.year
    months = end.month - start.month
    days = end.day - start.day

    if days < 0:
        months -= 1
    if months < 0:
        years -= 1
        months += 12

    return years, months


def calculate_n(years: int, months: int, monthly_salary: float,
                avg_salary_3x: Optional[float] = None) -> Dict:
    """
    计算经济补偿金 N

    Args:
        years: 工作年数
        months: 工作月数（剩余）
        monthly_salary: 月平均工资
        avg_salary_3x: 当地社平工资3倍（如提供则适用双封顶）

    Returns:
        包含 N, N+1, 2N 计算结果的字典
    """
    # 计算工作年限（用于补偿计算）
    if months >= 6:
        calc_years = years + 1
    elif months > 0:
        calc_years = years + 0.5
    else:
        calc_years = years

    # 双封顶处理
    if avg_salary_3x and monthly_salary > avg_salary_3x:
        calc_salary = avg_salary_3x
        calc_years = min(calc_years, 12)
        capped = True
    else:
        calc_salary = monthly_salary
        capped = False

    # 计算 N
    n = calc_years * calc_salary

    # N+1（代通知金按上月工资，假设等于平均工资）
    n_plus_1 = n + monthly_salary

    # 2N
    n_2 = n * 2

    return {
        'years': years,
        'months': months,
        'calc_years': calc_years,
        'monthly_salary': monthly_salary,
        'capped': capped,
        'capped_salary': calc_salary if capped else None,
        'N': round(n, 2),
        'N_plus_1': round(n_plus_1, 2),
        '2N': round(n_2, 2)
    }


def calculate_overtime(monthly_salary: float,
                       weekday_hours: float = 0,
                       weekend_days: float = 0,
                       holiday_days: float = 0) -> Dict:
    """
    计算加班费

    Args:
        monthly_salary: 月工资
        weekday_hours: 工作日延长加班小时数
        weekend_days: 休息日加班天数
        holiday_days: 法定节假日加班天数

    Returns:
        加班费明细字典
    """
    # 计算基数
    hour_salary = monthly_salary / 174  # 月计薪小时数 = 21.75 * 8 = 174
    day_salary = monthly_salary / 21.75  # 月计薪天数

    # 计算各类加班费
    weekday_pay = hour_salary * weekday_hours * 1.5
    weekend_pay = day_salary * weekend_days * 2
    holiday_pay = day_salary * holiday_days * 3

    total = weekday_pay + weekend_pay + holiday_pay

    return {
        'hour_salary': round(hour_salary, 2),
        'day_salary': round(day_salary, 2),
        'weekday_hours': weekday_hours,
        'weekend_days': weekend_days,
        'holiday_days': holiday_days,
        'weekday_pay': round(weekday_pay, 2),
        'weekend_pay': round(weekend_pay, 2),
        'holiday_pay': round(holiday_pay, 2),
        'total': round(total, 2)
    }


def calculate_double_wage(monthly_salary: float, months: int) -> Dict:
    """
    计算未签劳动合同双倍工资

    Args:
        monthly_salary: 月工资
        months: 未签合同月数（最多11个月）

    Returns:
        双倍工资计算结果
    """
    effective_months = min(months, 11)
    double_wage = monthly_salary * effective_months

    return {
        'monthly_salary': monthly_salary,
        'months': months,
        'effective_months': effective_months,
        'double_wage': round(double_wage, 2)
    }


def calculate_annual_leave_pay(monthly_salary: float, unused_days: int) -> Dict:
    """
    计算未休年假工资

    Args:
        monthly_salary: 月工资
        unused_days: 未休年假天数

    Returns:
        未休年假工资计算结果
    """
    day_salary = monthly_salary / 21.75
    leave_pay = day_salary * unused_days * 3  # 300%

    return {
        'day_salary': round(day_salary, 2),
        'unused_days': unused_days,
        'leave_pay': round(leave_pay, 2),
        'extra_pay': round(day_salary * unused_days * 2, 2)  # 额外200%
    }


def print_compensation_report(result: Dict):
    """打印经济补偿金计算报告"""
    print("\n" + "="*50)
    print("经济补偿金计算报告")
    print("="*50)
    print(f"工作年限: {result['years']}年{result['months']}个月")
    print(f"计算年限: {result['calc_years']}年")
    print(f"月平均工资: {result['monthly_salary']:.2f}元")

    if result['capped']:
        print(f"\n⚠️ 适用双封顶:")
        print(f"   月工资高于社平工资3倍，按 {result['capped_salary']:.2f}元 计算")
        print(f"   补偿年限最高12年")

    print(f"\n计算结果:")
    print(f"  N (经济补偿金): {result['N']:,.2f}元")
    print(f"  N+1 (含代通知金): {result['N_plus_1']:,.2f}元")
    print(f"  2N (违法解除赔偿金): {result['2N']:,.2f}元")

    print("\n适用情形:")
    print(f"  • N: 协商解除、合同到期不续签、经济性裁员等")
    print(f"  • N+1: 无过失性解除但未提前30日通知")
    print(f"  • 2N: 违法解除劳动合同")
    print("="*50)


def print_overtime_report(result: Dict):
    """打印加班费计算报告"""
    print("\n" + "="*50)
    print("加班费计算报告")
    print("="*50)
    print(f"小时工资: {result['hour_salary']:.2f}元")
    print(f"日工资: {result['day_salary']:.2f}元")

    print(f"\n加班情况:")
    if result['weekday_hours'] > 0:
        print(f"  工作日加班: {result['weekday_hours']}小时 × 150% = {result['weekday_pay']:,.2f}元")
    if result['weekend_days'] > 0:
        print(f"  休息日加班: {result['weekend_days']}天 × 200% = {result['weekend_pay']:,.2f}元")
    if result['holiday_days'] > 0:
        print(f"  法定节假日加班: {result['holiday_days']}天 × 300% = {result['holiday_pay']:,.2f}元")

    print(f"\n加班费合计: {result['total']:,.2f}元")
    print("="*50)


def interactive_mode():
    """交互式计算模式"""
    print("\n" + "="*50)
    print("劳动赔偿金计算器")
    print("="*50)
    print("\n请选择计算类型:")
    print("1. 经济补偿金 (N, N+1, 2N)")
    print("2. 加班费")
    print("3. 未签劳动合同双倍工资")
    print("4. 未休年假工资")
    print("5. 综合计算")
    print("0. 退出")

    choice = input("\n请输入选项 (0-5): ").strip()

    if choice == "1":
        print("\n--- 经济补偿金计算 ---")
        years = int(input("工作年数: "))
        months = int(input("剩余月数: "))
        salary = float(input("月平均工资: "))

        avg_3x = input("当地社平工资3倍 (如无请直接回车): ").strip()
        avg_3x = float(avg_3x) if avg_3x else None

        result = calculate_n(years, months, salary, avg_3x)
        print_compensation_report(result)

    elif choice == "2":
        print("\n--- 加班费计算 ---")
        salary = float(input("月工资: "))
        weekday = float(input("工作日加班小时数 (无则填0): ") or "0")
        weekend = float(input("休息日加班天数 (无则填0): ") or "0")
        holiday = float(input("法定节假日加班天数 (无则填0): ") or "0")

        result = calculate_overtime(salary, weekday, weekend, holiday)
        print_overtime_report(result)

    elif choice == "3":
        print("\n--- 未签劳动合同双倍工资 ---")
        salary = float(input("月工资: "))
        months = int(input("未签合同月数 (最多11个月): "))

        result = calculate_double_wage(salary, months)
        print(f"\n双倍工资: {result['double_wage']:,.2f}元")
        print(f"(计算月数: {result['effective_months']}个月)")

    elif choice == "4":
        print("\n--- 未休年假工资 ---")
        salary = float(input("月工资: "))
        days = int(input("未休年假天数: "))

        result = calculate_annual_leave_pay(salary, days)
        print(f"\n日工资: {result['day_salary']:.2f}元")
        print(f"未休年假工资: {result['leave_pay']:,.2f}元")
        print(f"(其中100%为正常工资已发，额外支付200%为 {result['extra_pay']:,.2f}元)")

    elif choice == "5":
        print("\n--- 综合计算 ---")
        years = int(input("工作年数: "))
        months = int(input("剩余月数: "))
        salary = float(input("月平均工资: "))

        avg_3x = input("当地社平工资3倍 (如无请直接回车): ").strip()
        avg_3x = float(avg_3x) if avg_3x else None

        print("\n请输入加班情况:")
        weekday = float(input("  工作日加班小时数 (无则填0): ") or "0")
        weekend = float(input("  休息日加班天数 (无则填0): ") or "0")
        holiday = float(input("  法定节假日加班天数 (无则填0): ") or "0")

        unused_leave = int(input("\n未休年假天数 (无则填0): ") or "0")

        # 计算各项
        comp_result = calculate_n(years, months, salary, avg_3x)
        ot_result = calculate_overtime(salary, weekday, weekend, holiday)
        leave_result = calculate_annual_leave_pay(salary, unused_leave)

        # 打印报告
        print_compensation_report(comp_result)
        print_overtime_report(ot_result)

        print("\n" + "="*50)
        print("未休年假工资报告")
        print("="*50)
        print(f"未休年假工资: {leave_result['leave_pay']:,.2f}元")

        # 总计
        total = comp_result['2N'] + ot_result['total'] + leave_result['leave_pay']
        print("\n" + "="*50)
        print("总计")
        print("="*50)
        print(f"2N赔偿金: {comp_result['2N']:,.2f}元")
        print(f"加班费: {ot_result['total']:,.2f}元")
        print(f"未休年假工资: {leave_result['leave_pay']:,.2f}元")
        print(f"\n总计: {total:,.2f}元")
        print("="*50)

    elif choice == "0":
        print("再见!")
        sys.exit(0)

    else:
        print("无效的选项")


def main():
    """主函数"""
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("""
劳动赔偿金计算器

使用方法:
  python calculate_compensation.py              # 交互模式
  python calculate_compensation.py --help       # 显示帮助

功能:
  1. 计算经济补偿金 (N, N+1, 2N)
  2. 计算加班费
  3. 计算未签劳动合同双倍工资
  4. 计算未休年假工资
  5. 综合计算

法律依据:
  - 《劳动合同法》第47、87条
  - 《劳动法》第44条
  - 《职工带薪年休假条例》第5条
        """)
        return

    # 默认进入交互模式
    while True:
        try:
            interactive_mode()
            again = input("\n是否继续计算? (y/n): ").strip().lower()
            if again != 'y':
                print("再见!")
                break
        except KeyboardInterrupt:
            print("\n\n再见!")
            break
        except ValueError as e:
            print(f"\n输入错误: {e}")
        except Exception as e:
            print(f"\n发生错误: {e}")


if __name__ == "__main__":
    main()
