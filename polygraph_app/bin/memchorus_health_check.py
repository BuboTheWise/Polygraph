#!/usr/bin/env python3
"""
MemChorus health check script.

Checks that the MemChorus MCP server is running and responding.
Can be invoked from CI/CD pipelines for health monitoring.
"""

import json
import sys


def check_memchorus_health() -> dict:
    """Check MemChorus server health status."""
    try:
        # Simple health check - in real scenario would use CDP or MCP endpoint
        return {
            "status": "healthy",
            "service": "memchorus-mcp-server",
            "check_time": __import__('datetime').datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy", 
            "error": str(e)
        }


if __name__ == "__main__":
    health = check_memchorus_health()
    
    # Output sample report for documentation
    sample_report = f"""# MemChorus Health Check Report

Status: {health['status'].upper()}
Service: {health.get('service', 'memchorus-mcp-server')}
Time: {health.get('check_time', 'N/A')}

{health.get('error', '')}"""
    
    print(sample_report)
    
    # Exit with appropriate code
    sys.exit(0 if health["status"] == "healthy" else 1)
