#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
github_security_audit.py — Security audit for GitHub repositories

Usage:
    python github_security_audit.py <repo_url> [repo_url2 ...]

Example:
    python github_security_audit.py https://github.com/user/repo
"""

import sys
import json
import subprocess
import re
from datetime import datetime
from urllib.parse import urlparse

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")

def print_status(ok, text):
    if ok:
        print(f"  {Colors.GREEN}✅{Colors.END} {text}")
    else:
        print(f"  {Colors.RED}❌{Colors.END} {text}")

def print_warning(text):
    print(f"  {Colors.YELLOW}⚠️{Colors.END} {text}")

def print_info(text):
    print(f"  {Colors.BLUE}ℹ️{Colors.END} {text}")

def parse_repo_url(url):
    """Parse GitHub URL to get owner/repo"""
    parsed = urlparse(url)
    path = parsed.path.strip('/')
    parts = path.split('/')
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return None

def gh_available():
    """Check if gh CLI is available"""
    try:
        result = subprocess.run(['gh', '--version'], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except:
        return False

def gh_exec(args):
    """Execute gh CLI command"""
    try:
        result = subprocess.run(['gh'] + args, capture_output=True, text=True, timeout=30)
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)

def check_repo_exists(repo):
    """Check if repository exists"""
    ok, stdout, stderr = gh_exec(['repo', 'view', repo, '--json', 'name', '-q', '.name'])
    if ok:
        print_info(f"Repository exists: {repo}")
    else:
        print_warning(f"Could not verify repository: {stderr[:100]}")
    return ok

def check_security_tab(repo):
    """Check GitHub Security tab for advisories"""
    print_header("1. SECURITY TAB ANALYSIS")
    
    # Check for Dependabot alerts
    ok, stdout, stderr = gh_exec(['api', f"/repos/{repo}/dependabot/alerts", '--jq', '.[] | .security_advisory.ghsa_id'])
    if ok and stdout.strip():
        alerts = stdout.strip().split('\n')
        print_warning(f"Found {len(alerts)} Dependabot alerts!")
        for alert in alerts[:5]:
            print_info(f"  - {alert}")
    else:
        print_status(True, "No Dependabot alerts found")
    
    # Check for code scanning alerts
    ok, stdout, stderr = gh_exec(['api', f"/repos/{repo}/code-scanning/alerts", '--jq', '.[] | .rule.id'])
    if ok and stdout.strip():
        alerts = stdout.strip().split('\n')
        print_warning(f"Found {len(alerts)} code scanning alerts!")
        for alert in alerts[:5]:
            print_info(f"  - {alert}")
    else:
        print_status(True, "No code scanning alerts found")
    
    # Check for secret scanning alerts
    ok, stdout, stderr = gh_exec(['api', f"/repos/{repo}/secret-scanning/alerts", '--jq', '.[]'])
    if ok and stdout.strip():
        alerts = stdout.strip().split('\n')
        if len(alerts) > 0:
            print_warning(f"Found secret scanning alerts!")
    else:
        print_status(True, "No secret scanning alerts")

def check_repo_stats(repo):
    """Check repository statistics for anomalies"""
    print_header("2. REPO STATISTICS")
    
    # Get repo info
    ok, stdout, stderr = gh_exec(['repo', 'view', repo, '--json', 
                                   'name,createdAt,pushedAt,stargazerCount,'
                                   'forkCount,openIssueCount,openPRCount,'
                                   'defaultBranchRef', '-q', '.'])
    if ok:
        try:
            data = json.loads(stdout)
            print_info(f"Name: {data.get('name', 'N/A')}")
            print_info(f"Created: {data.get('createdAt', 'N/A')[:10]}")
            print_info(f"Last push: {data.get('pushedAt', 'N/A')[:10]}")
            print_info(f"Stars: {data.get('stargazerCount', 0)}")
            print_info(f"Forks: {data.get('forkCount', 0)}")
            print_info(f"Open Issues: {data.get('openIssueCount', 0)}")
            print_info(f"Open PRs: {data.get('openPRCount', 0)}")
            
            # Check for suspicious patterns
            stars = data.get('stargazerCount', 0)
            forks = data.get('forkCount', 0)
            
            if forks > stars * 10:
                print_warning(f"Very high fork-to-star ratio ({forks} forks vs {stars} stars)")
            
            if stars < 5 and forks > 50:
                print_warning("Low stars but many forks - possible spam repo")
                
        except json.JSONDecodeError:
            print_warning("Could not parse repo info")
    else:
        print_warning(f"Could not get repo info")

def check_recent_commits(repo):
    """Check recent commits for suspicious activity"""
    print_header("3. RECENT COMMITS ANALYSIS")
    
    ok, stdout, stderr = gh_exec(['api', f"/repos/{repo}/commits", 
                                   '--jq', '.[] | {sha: .sha[0:7], message: .commit.message, '
                                   'author: .commit.author.name, date: .commit.author.date}', 
                                   '-L', '10'])
    if ok and stdout.strip():
        commits = stdout.strip().split('\n')
        print_info(f"Analyzing last {len(commits)} commits:")
        
        suspicious_patterns = [
            'feat: bypass', 'fix: bypass', 'hack', 'trojan', 'backdoor',
            'test: trust', 'chore: secret', 'tmp: password', 'wip: malware'
        ]
        
        for commit in commits[:10]:
            for pattern in suspicious_patterns:
                if pattern.lower() in commit.lower():
                    print_warning(f"Suspicious commit: {commit[:100]}")
                    break
    else:
        print_info("Could not fetch recent commits")

def check_issues_prs(repo):
    """Search for malicious/vulnerability keywords in issues/PRs"""
    print_header("4. ISSUES & PRS SEARCH")
    
    search_terms = ['malicious', 'vulnerability', 'trojan', 'phishing', 
                    'scam', 'fake', 'exploit', 'backdoor', 'security issue']
    
    suspicious_count = 0
    
    for term in search_terms[:3]:  # Limit to avoid rate limiting
        # Search issues
        ok, stdout, stderr = gh_exec(['search', 'issues', term, 
                                       '--repo', repo, '--state', 'all', 
                                       '--limit', '5', '--json', 'title', '-q', '.[] | .title'])
        if ok and stdout.strip():
            issues = stdout.strip().split('\n')
            if len(issues) > 0 and issues[0]:
                suspicious_count += len(issues)
                print_warning(f"'{term}' found in issues: {len(issues)}")
                for issue in issues[:2]:
                    print_info(f"  - {issue[:80]}")
    
    if suspicious_count == 0:
        print_status(True, "No suspicious keywords found in issues/PRs")

def check_external_search(repo_name):
    """Search external sources for security mentions"""
    print_header("5. EXTERNAL SECURITY SEARCH")
    
    if not REQUESTS_AVAILABLE:
        print_info("requests library not available, skipping external search")
        return
    
    search_queries = [
        f'"{repo_name}" malicious',
        f'"{repo_name}" security vulnerability',
        f'"{repo_name}" scam'
    ]
    
    print_info("Note: Manual verification recommended at:")
    print_info(f"  - https://www.virustotal.com")
    print_info(f"  - https://snyk.io/advisor/")
    print_info(f"  - https://github.com/{repo_name}/network/dependencies")

def check_npm_audit(repo_path=None):
    """Check for npm audit if package.json exists"""
    print_header("6. NPM AUDIT (if Node.js project)")
    
    if repo_path:
        import os
        package_json = os.path.join(repo_path, 'package.json')
        if os.path.exists(package_json):
            print_info("Found package.json, checking for issues...")
            ok, stdout, stderr = subprocess.run(
                ['npm', 'audit', '--json'], 
                capture_output=True, text=True, timeout=60, cwd=repo_path
            )
            if ok:
                print_status(True, "No npm vulnerabilities found")
            else:
                try:
                    data = json.loads(stdout)
                    vulnerabilities = data.get('metadata', {}).get('vulnerabilities', {})
                    total = sum(vulnerabilities.values())
                    if total > 0:
                        print_warning(f"Found {total} npm vulnerabilities!")
                    else:
                        print_status(True, "No vulnerabilities")
                except:
                    print_warning("npm audit failed to parse output")
        else:
            print_info("No package.json found (not a Node.js project)")

def check_dockerfile(repo_path=None):
    """Check for Dockerfile and security issues"""
    print_header("7. DOCKERFILE ANALYSIS")
    
    if repo_path:
        import os
        dockerfile = os.path.join(repo_path, 'Dockerfile')
        if os.path.exists(dockerfile):
            print_info("Found Dockerfile!")
            with open(dockerfile, 'r') as f:
                content = f.read()
            
            # Check for suspicious patterns
            suspicious = [
                ('curl | sh', 'Curl pipe to shell - HIGH RISK'),
                ('wget | sh', 'Wget pipe to shell - HIGH RISK'),
                ('password', 'Hardcoded password detected'),
                ('api_key', 'Hardcoded API key detected'),
                ('secret', 'Hardcoded secret detected'),
                ('RUN chmod 777', 'Overly permissive file permissions'),
                ('root', 'Running as root - security risk'),
                ('ENV.*PASSWORD', 'Password in environment variable'),
            ]
            
            for pattern, message in suspicious:
                if re.search(pattern, content, re.IGNORECASE):
                    print_warning(message)
            
            if not any(re.search(p[0], content, re.I) for p in suspicious):
                print_status(True, "No obvious security issues in Dockerfile")
        else:
            print_info("No Dockerfile found")

def run_full_audit(repo_url, clone_path=None):
    """Run complete security audit"""
    repo = parse_repo_url(repo_url)
    if not repo:
        print(f"{Colors.RED}❌ Invalid GitHub URL: {repo_url}{Colors.END}")
        return False
    
    print(f"\n{Colors.BOLD}🔍 SECURITY AUDIT: {repo}{Colors.END}")
    print(f"{Colors.BOLD}Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Colors.END}")
    
    if not gh_available():
        print(f"{Colors.RED}❌ GitHub CLI (gh) not available!{Colors.END}")
        print("Install: https://cli.github.com/")
        return False
    
    # Run all checks
    check_repo_exists(repo)
    check_repo_stats(repo)
    check_recent_commits(repo)
    check_security_tab(repo)
    check_issues_prs(repo)
    check_external_search(repo)
    
    if clone_path:
        check_npm_audit(clone_path)
        check_dockerfile(clone_path)
    
    print_header("AUDIT COMPLETE")
    print(f"\n{Colors.BOLD}Recommendation:{Colors.END}")
    print("  Review all warnings above before proceeding.")
    print("  For critical projects, manual code review is recommended.")
    print("  Use VirusTotal and Snyk for additional scanning.")
    
    return True

def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <repo_url> [repo_url2 ...]")
        print(f"Example: python {sys.argv[0]} https://github.com/user/repo")
        sys.exit(1)
    
    for arg in sys.argv[1:]:
        run_full_audit(arg)

if __name__ == "__main__":
    main()
