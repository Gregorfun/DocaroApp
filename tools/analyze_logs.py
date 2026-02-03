#!/usr/bin/env python3
"""
Docaro Log-Analyzer
Analysiert Logs fuer Performance-Metriken und Fehler-Statistiken
"""

import sys
import re
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import Config


class LogAnalyzer:
    def __init__(self, log_file: Path):
        self.log_file = log_file
        self.lines = []
        self.errors = defaultdict(int)
        self.timings = []
        self.suppliers = defaultdict(int)
        self.doc_types = defaultdict(int)
        
    def load(self):
        """Load log file"""
        if not self.log_file.exists():
            print(f"Log file not found: {self.log_file}")
            return False
        
        try:
            with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                self.lines = f.readlines()
            print(f"OK - {len(self.lines)} lines loaded")
            return True
        except Exception as e:
            print(f"Error reading log: {e}")
            return False
    
    def analyze(self):
        """Analyze logs"""
        print("\n" + "="*60)
        print("LOG ANALYSIS")
        print("="*60)
        
        for line in self.lines:
            if "ERROR" in line or "error" in line.lower():
                if "tesseract" in line.lower():
                    self.errors["OCR (Tesseract)"] += 1
                elif "supplier" in line.lower():
                    self.errors["Supplier Extraction"] += 1
                elif "date" in line.lower():
                    self.errors["Date Extraction"] += 1
                elif "quarantine" in line.lower():
                    self.errors["Quarantine"] += 1
                else:
                    self.errors["Other"] += 1
            
            timing_match = re.search(r'(\d+(?:\.\d+)?)\s*ms', line)
            if timing_match:
                try:
                    ms = float(timing_match.group(1))
                    self.timings.append(ms)
                except:
                    pass
            
            supplier_match = re.search(r'supplier["\']?\s*:\s*["\']?([^"\'}\n,]+)', line, re.IGNORECASE)
            if supplier_match:
                supplier = supplier_match.group(1).strip()
                if supplier and len(supplier) < 50:
                    self.suppliers[supplier] += 1
            
            doctype_match = re.search(r'doc_type["\']?\s*:\s*["\']?([^"\'}\n,]+)', line, re.IGNORECASE)
            if doctype_match:
                doctype = doctype_match.group(1).strip()
                if doctype and len(doctype) < 50:
                    self.doc_types[doctype] += 1
        
        self._print_summary()
        self._print_errors()
        self._print_performance()
        self._print_top_suppliers()
        self._print_doc_types()
    
    def _print_summary(self):
        print("\nSUMMARY")
        print(f"  Time range: {self.lines[0][:19] if self.lines else 'N/A'} - {self.lines[-1][:19] if self.lines else 'N/A'}")
        print(f"  Log entries: {len(self.lines)}")
        print(f"  Total errors: {sum(self.errors.values())}")
    
    def _print_errors(self):
        if not self.errors:
            print("\nERRORS: None found")
            return
        
        print("\nERRORS BY CATEGORY")
        for error_type, count in sorted(self.errors.items(), key=lambda x: x[1], reverse=True):
            pct = (count / len(self.lines)) * 100 if self.lines else 0
            print(f"  {error_type:25} {count:4d} ({pct:5.1f}%)")
    
    def _print_performance(self):
        if not self.timings:
            print("\nPERFORMANCE: No timing data")
            return
        
        print("\nPERFORMANCE")
        avg = sum(self.timings) / len(self.timings)
        min_t = min(self.timings)
        max_t = max(self.timings)
        
        sorted_timings = sorted(self.timings)
        p50 = sorted_timings[len(sorted_timings)//2]
        p95 = sorted_timings[int(len(sorted_timings)*0.95)]
        
        print(f"  Average:          {avg:8.1f} ms")
        print(f"  Median (P50):     {p50:8.1f} ms")
        print(f"  95th Percentile:  {p95:8.1f} ms")
        print(f"  Min / Max:        {min_t:8.1f} / {max_t:8.1f} ms")
        print(f"  Samples:          {len(self.timings):8d}")
    
    def _print_top_suppliers(self):
        if not self.suppliers:
            print("\nSUPPLIERS: No data")
            return
        
        print("\nTOP 10 SUPPLIERS")
        for supplier, count in sorted(self.suppliers.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"  {supplier:30} {count:4d}")
    
    def _print_doc_types(self):
        if not self.doc_types:
            print("\nDOC TYPES: No data")
            return
        
        print("\nDOCUMENT TYPES")
        for doctype, count in sorted(self.doc_types.items(), key=lambda x: x[1], reverse=True):
            pct = (count / sum(self.doc_types.values())) * 100
            print(f"  {doctype:25} {count:4d} ({pct:5.1f}%)")


def main():
    log_dir = Config.LOG_DIR
    
    if not log_dir.exists():
        print(f"Log directory not found: {log_dir}")
        return 1
    
    log_files = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    
    if not log_files:
        print(f"No log files in {log_dir}")
        return 1
    
    log_file = log_files[0]
    
    print(f"\nDOCAR LOG ANALYZER")
    print(f"Analyzing: {log_file.name}")
    
    analyzer = LogAnalyzer(log_file)
    if not analyzer.load():
        return 1
    
    analyzer.analyze()
    
    print("\n" + "="*60)
    print("OK - Analysis complete")
    print("="*60 + "\n")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
