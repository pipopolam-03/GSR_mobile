import pandas as pd
import os

annotations_file = "labels.csv"

data_folder = ""

output_folder = "labeled"
os.makedirs(output_folder, exist_ok=True)

annotations = pd.read_csv(annotations_file)

for _, row in annotations.iterrows():

    filename = row["filename"]
    path = os.path.join(data_folder, filename)

    df = pd.read_csv(path)

    # перевод Unix ms в UTC+3
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df["datetime"] = df["datetime"].dt.tz_convert("Etc/GMT-3")

    df["time"] = df["datetime"].dt.time

    split1 = pd.to_datetime(row["split_1"]).time()
    split2 = pd.to_datetime(row["split_2"]).time()

    activity1 = row["activity_1"]
    activity2 = row["activity_2"]
    activity3 = row["activity_3"]

    intervals = []
    labels = []

    for t in df["time"]:

        if t < split1:
            intervals.append(0)
            labels.append(activity1)

        elif split1 <= t < split2:
            intervals.append(1)
            labels.append(activity2)

        else:
            intervals.append(2)
            labels.append(activity3)

    df["interval"] = intervals
    df["label"] = labels

    df = df[[ "time", "gsr", "ecg", "interval", "label"]]

    save_path = os.path.join(output_folder, filename)
    df.to_csv(save_path, index=False)

    print("Saved:", save_path)

print("Готово")