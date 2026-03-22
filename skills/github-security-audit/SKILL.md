# GitHub Security Audit Skill

## Description

Performs comprehensive security audits on GitHub repositories before clone or pull. Checks for vulnerabilities, malicious code patterns, and suspicious activity.

## Usage

```bash
python skills/github-security-audit/github_security_audit.py <repo_url>
```

## What it checks

### 1. Security Tab Analysis
- Dependabot alerts
- Code scanning alerts
- Secret scanning alerts

### 2. Repository Statistics
- Stars, forks, issues
- Creation date
- Last push date
- Suspicious patterns (high fork ratio, low stars)

### 3. Recent Commits
- Checks for suspicious commit messages
- Patterns: bypass, trojan, backdoor, hack, etc.

### 4. Issues & PRs Search
- Searches for malicious/vulnerability keywords
- Phishing, scam, exploit patterns

### 5. External Security Search
- VirusTotal links
- Snyk advisor
- GitHub dependency graph

### 6. NPM Audit (Node.js)
- If package.json exists, runs npm audit

### 7. Dockerfile Analysis
- curl | sh patterns (HIGH RISK)
- Hardcoded passwords/secrets
- Overly permissive permissions

## Example Output

```
🔍 SECURITY AUDIT: user/repo
  ✅ No Dependabot alerts found
  ✅ No code scanning alerts found
  ✅ No suspicious keywords in issues/PRs
```

## Integration

Add to workspace for automatic security checks before git operations.

## Requirements

- GitHub CLI (gh) installed and authenticated
- Optional: npm for Node.js projects
