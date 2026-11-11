import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from SASTs.Codeql import Codeql
from SASTs.Pysa import Pysa
from SASTs.Semgrep import Semgrep
from SASTs.Bandit import Bandit
from SASTs.Snyk import Snyk
from SASTs.Bearer import Bearer
from SASTs.DevSkim import DevSkim
from SASTs.Dlint import Dlint

import time
import argparse

log = ""

# TEMP: path updated from the authors' machine to local clone
Project_Root = "/Users/chacenuttall/Documents/PySASTBench/"
Synthetic_dataset_path = Project_Root + "SyntheticDataset/"
Experiment_Root = Project_Root + "Synthetic_experiment/"

# TEMP: limit the run to one CWE folder while verifying the pipeline.
# Set to None to run all six.
CWE_FILTER = None


def Log(message:str):
    current_time = time.asctime(time.localtime(time.time()))
    
    message = current_time + " " + message + "\n"
    
    log.write(message)
    log.flush()
    

def prepare_outpath(sast, target):
    
    case_name = os.path.basename(target)
    case_name = case_name.split(".")[0]
    
    out_dir = Experiment_Root + sast + "/"
    
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    
    output = ""
    if sast == "Codeql":
        output = out_dir + case_name + ".csv"
    elif sast == "Pysa":
        output = out_dir + case_name
    elif sast == "Semgrep":
        output = out_dir + case_name + ".json"
    elif sast == "Bandit":
        output = out_dir + case_name + ".json"
    elif sast == "Snyk":
        output = out_dir + case_name + ".json"
    elif sast == "Bearer":
        output = out_dir + case_name + ".json"
    elif sast == "DevSkim":
        output = out_dir + case_name + ".json"
    elif sast == "Dlint":
        output = out_dir + case_name + ".txt"
    
    return output


def do_test(sast:str, targets):
    
    ltime = []
    
    test_func = ""
    if sast == "Codeql":
        test_func = Codeql()
    elif sast == "Pysa":
        config = Project_Root + "scripts/auto_pysa.tcl"
        test_func = Pysa(config)
    elif sast == "Semgrep":
        test_func = Semgrep()
    elif sast == "Bandit":
        test_func = Bandit()
    elif sast == "Snyk":
        test_func = Snyk()
    elif sast == "Bearer":
        test_func = Bearer()
    elif sast == "DevSkim":
        test_func = DevSkim()
    elif sast == "Dlint":
        test_func = Dlint()
    
    
    left = len(targets)
    for target in targets:

        left -= 1
        Log("TESTING " + target + ", " + str(left) + " targets left")
        # TEMP: progress to stdout so the run is visible while it works
        print("TESTING " + os.path.basename(target) + ", " + str(left) + " left")

        output = prepare_outpath(sast, target)

        total_time = test_func(target, output)

        if total_time == 0:
            Log("Already tested, skipped")

        if total_time == -1:
            Log("An error raised, skipped")
            ltime.append(0)
            continue

        ltime.append(total_time)
        Log("TESTED " + target + ", " + str(total_time) + " seconds taken, " + str(left) + " targets left")
    
    tmp = 0
    for i in ltime:
        tmp += i
    Log("Took " + str(tmp) + " seconds to test")
    # TEMP: echo the total to stdout as well
    print("Done. Took " + str(tmp) + " seconds.")



if __name__=='__main__':
    
    parser = argparse.ArgumentParser(description="Evaluate SAST with Synthetic Dataset!")
    parser.add_argument("sast", type=str, help="SAST to evaluate. Codeql, Pysa, Bandit, Semgrep, Snyk, Bearer, DevSkim are available.")
    
    args = parser.parse_args()
    
    sast = args.sast
    
    # TEMP: create the log directory if it does not exist
    os.makedirs("./logs", exist_ok=True)
    
    # TEMP: filename-safe timestamp (the original used asctime,
    # which contains spaces and colons)
    now = time.strftime("%Y%m%d_%H%M%S", time.localtime(time.time()))
    logfile = "./logs/log_synthetic_"+sast+"_"+now
    log = open(logfile, "w")
    
    targets = []
    for cwe in os.listdir(Synthetic_dataset_path):
        cwe_path = Synthetic_dataset_path + cwe + "/"
        
        # TEMP: skip non-directories such as .DS_Store on macOS
        if not os.path.isdir(cwe_path):
            continue
        
        # TEMP: apply the CWE filter
        if CWE_FILTER is not None and cwe != CWE_FILTER:
            continue
        
        for case in os.listdir(cwe_path):
            # TEMP: only Python source files
            if not case.endswith(".py"):
                continue
            case_path = cwe_path + case
            targets.append(case_path)

    #TEMP: sorted for deterministic ordering, count instead of full dump
    targets.sort()
    print("Found " + str(len(targets)) + " targets")
    
    do_test(sast, targets)
