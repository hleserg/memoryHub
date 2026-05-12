#!/usr/bin/env python3
"""
Script to automatically update test files for SessionExperience refactoring.

Changes:
- key_moments=[...] → key_moment_ids=[moment.id]
- Add avg_emotional_intensity and has_profound_moment fields
"""

import re
import sys
from pathlib import Path


def fix_session_experience_calls(content: str) -> str:
    """Fix SessionExperience constructor calls."""
    
    # Pattern 1: Simple single moment case: key_moments=[moment]
    # Replace with: key_moment_ids=[moment.id], avg_emotional_intensity=..., has_profound_moment=...
    
    # For now, use default values
    pattern1 = r'SessionExperience\((.*?)key_moments=\[([a-zA-Z_][a-zA-Z0-9_]*)\](.*?)\)'
    
    def replace1(match):
        before = match.group(1)
        moment_var = match.group(2)
        after = match.group(3)
        
        # Add new fields with reasonable defaults
        return f'SessionExperience({before}key_moment_ids=[{moment_var}.id], avg_emotional_intensity=0.5, has_profound_moment=False{after})'
    
    content = re.sub(pattern1, replace1, content, flags=re.DOTALL)
    
    return content


def process_file(filepath: Path) -> tuple[bool, str]:
    """Process a single test file."""
    try:
        content = filepath.read_text(encoding='utf-8')
        original = content
        
        # Apply fixes
        content = fix_session_experience_calls(content)
        
        if content != original:
            filepath.write_text(content, encoding='utf-8')
            return True, f"Updated {filepath}"
        else:
            return False, f"No changes needed in {filepath}"
            
    except Exception as e:
        return False, f"Error processing {filepath}: {e}"


def main():
    """Main entry point."""
    tests_dir = Path("/workspace/tests")
    
    if not tests_dir.exists():
        print(f"Tests directory not found: {tests_dir}")
        sys.exit(1)
    
    # Find all test files
    test_files = list(tests_dir.rglob("test_*.py"))
    
    print(f"Found {len(test_files)} test files")
    print()
    
    updated_count = 0
    for test_file in sorted(test_files):
        changed, message = process_file(test_file)
        if changed:
            updated_count += 1
            print(f"✓ {message}")
        else:
            print(f"  {message}")
    
    print()
    print(f"Updated {updated_count}/{len(test_files)} files")


if __name__ == "__main__":
    main()
