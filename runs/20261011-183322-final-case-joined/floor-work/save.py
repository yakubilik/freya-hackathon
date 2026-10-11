"""python3 save.py out/workflow.json: dry run on the platform, then save into this run's slot."""
import json, sys
sys.path.insert(0, "kit")
import freya
run = json.load(open("run.json"))
wf = json.load(open(sys.argv[1]))
try:
    freya.validate_workflow(run["slot"] + " dry run", wf)
except Exception as e:
    sys.exit("dry run rejected the workflow: %s" % str(e)[:3000])
print(json.dumps(freya.save_workflow(run["slot"], wf, state_file=run["state_file"])))
