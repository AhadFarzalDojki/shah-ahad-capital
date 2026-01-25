# analyze_market_regimes.py

import pandas as pd
from datetime import datetime, timedelta
import logging
from collections import Counter
import os
import numpy as np # For np.nan

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_valid_analysis_date_range() -> tuple[datetime, datetime] or tuple[None, None]:
    """Prompts the user to enter a start and end date for regime analysis."""
    start_date, end_date = None, None
    while True:
        start_date_str = input("Enter the START date for regime analysis (YYYY-MM-DD): ")
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            break
        except ValueError:
            print("Invalid start date format. Please use YYYY-MM-DD.")

    while True:
        end_date_str = input("Enter the END date for regime analysis (YYYY-MM-DD): ")
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
            if end_date < start_date:
                print("End date cannot be before the start date.")
                continue
            break
        except ValueError:
            print("Invalid end date format. Please use YYYY-MM-DD.")
    return start_date, end_date

def load_local_market_data(directory: str = r'C:\Users\shahr\Downloads\Shahad Capital\Market Regime Analysis',
                           filename: str = 'SPY-VIX_data.csv') -> pd.DataFrame or None:
    """Loads market data from a local CSV file, adapted for the provided image structure."""
    full_path = os.path.join(directory, filename)
    try:
        if not os.path.exists(full_path):
            logging.error(f"Data file '{full_path}' not found. Please run the 'fetch_market_data.py' script first.")
            return None
        
        data = pd.read_csv(
            full_path,
            header=0,
            skiprows=[1, 2],
            index_col=0,
            parse_dates=[0]
        )
        
        data.index.name = 'Date'
        
        logging.info(f"Successfully loaded data from {full_path} using image-based structure.")
        logging.info(f"Loaded DataFrame columns: {data.columns.tolist()}")
        return data
    except ValueError as ve:
        logging.error(f"ValueError loading data from {full_path}. This might be due to issues parsing dates from the first column or incorrect CSV structure: {ve}", exc_info=True)
        return None
    except Exception as e:
        logging.error(f"General error loading data from {full_path}: {e}", exc_info=True)
        return None

def calculate_regimes_from_local_data(start_date: datetime,
                                       end_date: datetime,
                                       loaded_data: pd.DataFrame,
                                       index_ticker_name: str = 'SPY',
                                       vix_ticker_name: str = '^VIX'
                                       ) -> list:
    """
    Determines market regime for each day using pre-loaded local data, including
    50-day and 200-day SMA analysis for Golden/Death Crosses.
    """
    daily_regimes = []
    
    spy_close_col = f'{index_ticker_name}_Close'
    spy_sma50_col = f'{index_ticker_name}_SMA_50'
    spy_sma200_col = f'{index_ticker_name}_SMA_200'
    vix_close_col = f'{vix_ticker_name}_Close'

    required_cols = [spy_close_col, spy_sma50_col, spy_sma200_col, vix_close_col]
    missing_cols = [col for col in required_cols if col not in loaded_data.columns]
    if missing_cols:
        logging.error(f"Missing required columns in loaded data: {', '.join(missing_cols)}. Please run the updated fetch_market_data.py script.")
        return [{"date": d.strftime('%Y-%m-%d'), "regime": f"Error: Missing columns ({', '.join(missing_cols)})", "indicators": {}}
                for d in pd.date_range(start_date, end_date)]
    
    previous_day_data = loaded_data.shift(1)

    current_iter_date = start_date
    while current_iter_date <= end_date:
        target_date_ts = pd.Timestamp(current_iter_date)
        regime = "Undefined"
        indicator_values = {"Target Date": current_iter_date.strftime('%Y-%m-%d')}

        try:
            if target_date_ts in loaded_data.index:
                data_for_day = loaded_data.loc[target_date_ts]
                prev_day = previous_day_data.loc[target_date_ts]

                last_price = data_for_day.get(spy_close_col, np.nan)
                last_sma_50 = data_for_day.get(spy_sma50_col, np.nan)
                last_sma_200 = data_for_day.get(spy_sma200_col, np.nan)
                last_vix = data_for_day.get(vix_close_col, np.nan)
                
                prev_sma_50 = prev_day.get(spy_sma50_col, np.nan)
                prev_sma_200 = prev_day.get(spy_sma200_col, np.nan)

                indicator_values["Actual Data Date"] = target_date_ts.strftime('%Y-%m-%d')
                indicator_values[f"{index_ticker_name} Price"] = f"{last_price:.2f}" if pd.notna(last_price) else "N/A"
                indicator_values[f"{index_ticker_name} 50-day SMA"] = f"{last_sma_50:.2f}" if pd.notna(last_sma_50) else "N/A"
                indicator_values[f"{index_ticker_name} 200-day SMA"] = f"{last_sma_200:.2f}" if pd.notna(last_sma_200) else "N/A"
                indicator_values[f"{vix_ticker_name} Level"] = f"{last_vix:.2f}" if pd.notna(last_vix) else "N/A"

                if pd.isna(last_price) or pd.isna(last_sma_50) or pd.isna(last_sma_200) or pd.isna(last_vix) or pd.isna(prev_sma_50) or pd.isna(prev_sma_200):
                    regime = "Insufficient Data for Full Analysis"
                else:
                    # --- Regime Logic ---
                    is_golden_cross = last_sma_50 > last_sma_200 and prev_sma_50 <= prev_sma_200
                    is_death_cross = last_sma_50 < last_sma_200 and prev_sma_50 >= prev_sma_200

                    # --- MODIFIED SECTION ---
                    # 1. Check for primary cross signals first. These are one-day signals.
                    if is_golden_cross:
                        regime = "Bull (Golden Cross Signal)"
                    elif is_death_cross:
                        regime = "Bear (Death Cross Signal)"
                    # 2. If no cross today, determine ongoing regime by price vs 200-day SMA and VIX
                    else:
                        price_above_200_sma = last_price > last_sma_200
                        price_below_200_sma = last_price < last_sma_200

                        if price_above_200_sma:
                            if last_vix < 18: regime = "Bull Quiet"
                            else: regime = "Bull Volatile"
                        elif price_below_200_sma:
                            if last_vix > 30: regime = "Bear Volatile (Crash)"
                            elif last_vix > 20: regime = "Bear Volatile"
                            else: regime = "Bear Quiet"
                        else:
                            if last_vix < 15: regime = "Sideways Quiet"
                            else: regime = "Sideways Volatile (Choppy)"
            else:
                regime = "No Data in Local File for this Date"
                indicator_values["Actual Data Date"] = "N/A"

        except KeyError:
            regime = "Error: Date not found in local data index"
            indicator_values["Actual Data Date"] = "N/A"
        except Exception as e:
            logging.error(f"Error processing date {current_iter_date.strftime('%Y-%m-%d')}: {e}", exc_info=True)
            regime = f"Error: Processing ({e})"

        daily_regimes.append({
            "date": current_iter_date.strftime('%Y-%m-%d'),
            "regime": regime,
            "indicators": indicator_values
        })
        current_iter_date += timedelta(days=1)
    return daily_regimes

# --- Main Execution ---
if __name__ == "__main__":
    market_data = load_local_market_data()

    if market_data is not None and not market_data.empty:
        start_analysis_date, end_analysis_date = get_valid_analysis_date_range()

        if start_analysis_date and end_analysis_date:
            all_results = calculate_regimes_from_local_data(start_analysis_date, end_analysis_date, market_data)

            print("\n\n---=== Daily Regime Analysis Results ===---")
            regime_counts = Counter()
            error_count = 0
            no_data_count = 0
            insufficient_data_count = 0
            
            # --- MODIFIED SECTION: Lists to track signal dates ---
            golden_cross_dates = []
            death_cross_dates = []

            for result in all_results:
                print(f"\n--- Date: {result['date']} ---")
                if "indicators" in result and result["indicators"]:
                    for key, value in result["indicators"].items():
                        print(f"{key}: {value}")
                print(f"Identified Market Regime: {result['regime']}")

                regime_str = result['regime']
                
                # --- MODIFIED SECTION: Check for signals to report in summary ---
                if "Golden Cross" in regime_str:
                    golden_cross_dates.append(result['date'])
                elif "Death Cross" in regime_str:
                    death_cross_dates.append(result['date'])

                if "Error" in regime_str:
                    error_count += 1
                elif "No Data" in regime_str:
                    no_data_count +=1
                elif "Insufficient Data" in regime_str:
                    insufficient_data_count += 1
                elif regime_str != "Undefined":
                    regime_counts[regime_str] += 1

            print("\n\n---=== Overall Period Summary ===---")
            print(f"Analysis Period: {start_analysis_date.strftime('%Y-%m-%d')} to {end_analysis_date.strftime('%Y-%m-%d')}")
            total_days_analyzed = len(all_results)
            print(f"Total Days Analyzed (calendar days): {total_days_analyzed}")
            print(f"Days with Processing Errors: {error_count}")
            print(f"Days with No Data in Local File (e.g., weekends/holidays): {no_data_count}")
            print(f"Days with Insufficient Data (e.g., missing SMA values): {insufficient_data_count}")

            # --- MODIFIED SECTION: Report specific signal dates ---
            if golden_cross_dates:
                print(f"Key Signal - Golden Cross occurred on: {', '.join(golden_cross_dates)}")
            if death_cross_dates:
                print(f"Key Signal - Death Cross occurred on: {', '.join(death_cross_dates)}")

            if regime_counts:
                valid_regime_days = sum(regime_counts.values())
                print(f"\nTotal Days with Valid Regime Identified: {valid_regime_days}")
                print("\nRegime Distribution over the period (for days with valid data):")
                for regime, count in regime_counts.most_common():
                    percentage = (count / valid_regime_days) * 100 if valid_regime_days > 0 else 0
                    print(f"- {regime}: {count} days ({percentage:.1f}%)")

                most_frequent_regime = regime_counts.most_common(1)[0][0] if regime_counts else "N/A"
                print(f"\nMost Frequent Regime (among valid days): {most_frequent_regime}")
                
               # --- Suggested Overall Stance based on Most Frequent Regime ---
print("\n--- Suggested Overall Stance based on Most Frequent Regime ---")

if most_frequent_regime == "Bull Quiet":
    print("Overall Stance: Generally favorable with low volatility. A steady uptrend is ideal for growth-focused strategies.")
    print("Suggested Strategies:")
    print("- Trend-Following: Capitalize on the established upward trend. Consider using moving averages to guide entries.")
    print("- Be Long-Biased: This is a market to be invested in. Maintain or increase long exposure.")
    print("- Buy on Dips: Use minor pullbacks and periods of consolidation as opportunities to add to positions.")
    print("- Increase Exposure: Given the low risk of sharp reversals, consider carefully increasing your overall risk.")

elif most_frequent_regime == "Bull Volatile":
    print("Overall Stance: Cautiously optimistic. The market is trending up but with higher risk of sharp reversals.")
    print("Suggested Strategies:")
    print("- Risk Management is Key: Protect gains with tighter stop-losses or hedging strategies.")
    print("- Reduce Position Sizing: Mitigate the impact of sudden price swings by using smaller position sizes.")
    print("- Momentum & Breakout Trades: These can be effective, but require wider stops to avoid being shaken out.")
    print("- Active Management: Be more hands-on, as the market direction can change quickly. Consider taking partial profits on strength.")

elif most_frequent_regime == "Bear Quiet":
    print("Overall Stance: Generally unfavorable. The market is in a slow, grinding downtrend. Capital preservation is the primary goal.")
    print("Suggested Strategies:")
    print("- Defensive Posturing: Focus on defensive assets, low-volatility stocks, or assets less correlated with the broader market.")
    print("- Raise Cash: Increase your cash allocation to buffer against further declines and prepare for future opportunities.")
    print("- Short-Selling: Consider strategies that profit from a declining market, but note that low volatility may mean a slow grind.")
    print("- Avoid Bottom Fishing: Resist the urge to buy, as the trend is working against you.")

elif most_frequent_regime == "Bear Volatile" or "Bear Volatile (Crash)":
    print("Overall Stance: Highly unfavorable and risky. The market is in a clear downtrend with high volatility and sharp price drops.")
    print("Suggested Strategies:")
    print("- Extreme Caution: For most, the best action is to significantly reduce exposure or stay on the sidelines.")
    print("- Do Not 'Buy the Dip': This can be a destructive strategy. Rallies are often short-lived bull traps.")
    print("- Volatility-Based Strategies: For experienced traders, strategies designed to profit from high volatility (e.g., options) can be considered.")
    print("- Diversify: Ensure your portfolio has exposure to non-correlated assets like government bonds or gold if appropriate for your mandate.")

elif most_frequent_regime == "N/A":
    print("Overall Stance: Cannot be determined due to lack of valid regime data.")
    print("Suggested Strategies: Adopt a neutral stance. Reduce risk and wait for a clearer trend and volatility pattern to emerge.")

else:
    # This else block will catch any regime names that are not explicitly handled above.
    print(f"Overall Stance: Interpretation for the regime '{most_frequent_regime}' needs to be defined.")
    print("Suggested Strategies: Proceed with caution until this market environment is better understood.")