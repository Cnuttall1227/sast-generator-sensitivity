import os
import pandas as pd
import json
import ast
from parsers import *
import argparse

# Changed: local path
Project_Root = "/Users/chacenuttall/Documents/PySASTBench/"
Experiment_Root = "/Users/chacenuttall/Documents/Se3994/results/gpt-sol-6-1/"
Synthetic_dataset_path = "/Users/chacenuttall/Documents/Se3994/corpus/GPT-Sol-6-1/"
CWEMapping_Root = Project_Root + "CWEMapping/"

GroundTruthPath = "/Users/chacenuttall/Documents/Se3994/corpus/gpt_groundtruth.json"
Ori_Ground_Truth_path = "/Users/chacenuttall/Documents/Se3994/corpus/chatgpt_groundtruth.csv"


def getGroundTruth(GroundTruthPath):
    if os.path.exists(GroundTruthPath):
        with open(GroundTruthPath) as f:
            groundTruth = json.load(f)
            return groundTruth
    
    groundTruth = {}
    
    # Temp: utf-8-sig strips the BOM on the TestCase column
    df = pd.read_csv(Ori_Ground_Truth_path, encoding='utf-8-sig')
    
    for index, row in df.iterrows():
        case_name = row['TestCase']
        location = row['Vul Position']
        cwe = row['CWE Type']
        groundTruth[case_name] = {
            "cwe": str(cwe),
            "location": location
        }
    
    with open(GroundTruthPath, 'w') as f:
        json.dump(groundTruth, f)
    
    return groundTruth


def getCWEMapping(mapping_file):
    
    cwe_mapping = {}
    
    f = open(mapping_file)
    content = f.readlines()
    for line in content:
        line = line.split(';')
        descript = line[0].strip()
        if len(line) == 1:
            # not cwe in selected categories
            cwe_mapping[descript] = [""]
            continue
        cwe = line[1].strip()
        cwe_mapping[descript] = cwe.split(",")
    f.close()
    return cwe_mapping


def main():
    
    parser = argparse.ArgumentParser(description="Evaluate SAST with Synthetic Dataset!")
    parser.add_argument("sast", type=str, help="SAST to evaluate. Codeql, Pysa, Bandit, Semgrep, Snyk, Bearer, DevSkim are available.")
    parser.add_argument("mode", type=str, help="collect or evaluate")
    
    args = parser.parse_args()
    
    sast = args.sast
    mode = args.mode

    parser = None
    if sast == 'Codeql':
        parser = Codeql_parser()
        
    if sast == 'Pysa':
        parser = Pysa_parser()
        
    if sast == 'Semgrep':
        parser = Semgrep_parser()
        
    if sast == 'Snyk':
        parser = Snyk_parser()
    
    if sast == 'Bandit':
        parser = Bandit_parser()
        
    if sast == 'DevSkim':
        parser = DevSkim_parser()
    
    if sast == 'Bearer':
        parser = Bearer_parser()
        
    if sast == 'Dlint':
        parser = Dlint_parser()
    
    report_dir = Experiment_Root + sast
    mapping_file = CWEMapping_Root + sast + ".txt"
    
    if mode == "collect":
        #sast_all_rep = ALLReports_Root_Dir + sast + '.txt'
        parser.collect(report_dir, mapping_file)
        return
    
    if mode == "evaluate":
        cwe_mapping = getCWEMapping(mapping_file)
        ground_truth = getGroundTruth(GroundTruthPath)
        parser.evaluate(report_dir, ground_truth, cwe_mapping, Synthetic_dataset_path)
        return




if __name__ == "__main__":
    main()