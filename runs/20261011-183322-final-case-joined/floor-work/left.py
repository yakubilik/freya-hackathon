import json, time
print(max(0, int(json.load(open("run.json"))["deadline_epoch"] - time.time())))
