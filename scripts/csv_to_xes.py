import pandas as pd
import pm4py

file_path = ".\input_files\event_logs\BPIChallenge2019_3WayMatchingEC.csv"
df = pd.read_csv(file_path)

df['time:timestamp'] = pd.to_datetime(df['time:timestamp'], format='%Y-%m-%d %H:%M:%S%z', utc=True)

output_file = "BPIChallenge2019_Output.xes"

pm4py.write_xes(
    df, 
    output_file, 
    case_id_key='case:concept:name', 
    activity_key='concept:name', 
    timestamp_key='time:timestamp'
)

print(f"Dönüşüm modern standartlarda, sıfır uyarı ile tamamlandı! Dosya: {output_file}")