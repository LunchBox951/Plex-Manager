import os
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum

# Environment mode (development vs production)
print_mode = os.environ.get('ENV', 'production')

# Thread lock for safe file writing
_log_lock = threading.Lock()


class Colors:
    """ANSI color codes for terminal output."""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


class LogLevel(Enum):
    """Log level enumeration for filtering."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"
    MONITOR = "MONITOR"
    FAILURE = "FAILURE"
    AUDIT = "AUDIT"


def _get_timestamp():
    """Get formatted timestamp string."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _get_log_file_path():
    """Get the path to today's log file."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_dir = Path(__file__).parent.parent / "data"
    return log_dir / f"{date_str}-console.log"


def _strip_ansi(text):
    """Remove ANSI color codes from text."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


def _write_log(level: LogLevel, message: str, prefix: str = None):
    """Write a log entry to the daily log file (thread-safe)."""
    with _log_lock:
        try:
            log_file = _get_log_file_path()
            log_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Format: [timestamp] [LEVEL] [prefix] message
            timestamp = _get_timestamp()
            prefix_str = f"[{prefix}] " if prefix else ""
            clean_message = _strip_ansi(message)
            log_entry = f"[{timestamp}] [{level.value}] {prefix_str}{clean_message}\n"
            
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception as e:
            # If logging fails, print to console but don't crash
            print(f"Failed to write log: {e}")


def print_info(message: str, prefix: str = None, timestamp: bool = True):
    """Print an informational message to the console."""
    ts = f"[{_get_timestamp()}] " if timestamp else ""
    prefix_str = f"[{prefix}] " if prefix else ""
    output = f"{ts}{Colors.CYAN}ℹ{Colors.ENDC} {prefix_str}{message}"
    print(output)
    _write_log(LogLevel.INFO, message, prefix)


def print_success(message: str, prefix: str = None, timestamp: bool = True):
    """Print a success message to the console."""
    ts = f"[{_get_timestamp()}] " if timestamp else ""
    prefix_str = f"[{prefix}] " if prefix else ""
    output = f"{ts}{Colors.GREEN}✓{Colors.ENDC} {prefix_str}{message}"
    print(output)
    _write_log(LogLevel.SUCCESS, message, prefix)


def print_warning(message: str, prefix: str = None, timestamp: bool = True):
    """Print a warning message to the console."""
    ts = f"[{_get_timestamp()}] " if timestamp else ""
    prefix_str = f"[{prefix}] " if prefix else ""
    output = f"{ts}{Colors.YELLOW}⚠{Colors.ENDC} {prefix_str}{message}"
    print(output)
    _write_log(LogLevel.WARNING, message, prefix)


def print_error(message: str, prefix: str = None, timestamp: bool = True):
    """Print an error message to the console."""
    ts = f"[{_get_timestamp()}] " if timestamp else ""
    prefix_str = f"[{prefix}] " if prefix else ""
    output = f"{ts}{Colors.RED}✗{Colors.ENDC} {prefix_str}{message}"
    print(output)
    _write_log(LogLevel.ERROR, message, prefix)


def print_debug(message: str, prefix: str = None, timestamp: bool = True):
    """Print a debug message to the console (only in development mode)."""
    # Always write to log file
    _write_log(LogLevel.DEBUG, message, prefix)
    
    # Only print to console in development mode
    if print_mode == 'development':
        ts = f"[{_get_timestamp()}] " if timestamp else ""
        prefix_str = f"[{prefix}] " if prefix else ""
        output = f"{ts}{Colors.BLUE}🔧{Colors.ENDC} {prefix_str}{message}"
        print(output)


def print_monitor(message: str = "", data: dict = None, prefix: str = None, timestamp: bool = True):
    """Print a monitor message with optional structured data (dev-only console, always logged)."""
    # If message is actually a dict (backwards compat for data-only calls), treat it as data
    if isinstance(message, dict) and data is None:
        data = message
        message = ""
    
    # Format structured data if provided
    if data:
        data_str = " | ".join([f"{k}: {v}" for k, v in data.items()])
        if message:
            full_message = f"{message} | {data_str}"
        else:
            full_message = data_str
    else:
        full_message = message
    
    # Use provided prefix or default to MONITOR
    log_prefix = prefix if prefix else "MONITOR"
    
    # Always write to log file
    _write_log(LogLevel.MONITOR, full_message, log_prefix)
    
    # Only print to console in development mode
    if print_mode == 'development':
        ts = f"[{_get_timestamp()}] " if timestamp else ""
        prefix_str = f"[{log_prefix}] " if log_prefix else "[MONITOR] "
        output = f"{ts}{Colors.CYAN}{prefix_str}{Colors.ENDC}{full_message}"
        print(output)


def print_failure(message: str, data: dict = None, prefix: str = None, timestamp: bool = True):
    """Print a failure message with optional structured data (always shown)."""
    # Format structured data if provided
    if data:
        data_str = " | ".join([f"{k}: {v}" for k, v in data.items()])
        full_message = f"{message} | {data_str}"
    else:
        full_message = message
    
    # Use provided prefix or default to FAILURE
    log_prefix = prefix if prefix else "FAILURE"
    
    ts = f"[{_get_timestamp()}] " if timestamp else ""
    prefix_str = f"[{log_prefix}]"
    output = f"{ts}{Colors.RED}{prefix_str}{Colors.ENDC} {full_message}"
    print(output)
    _write_log(LogLevel.FAILURE, full_message, log_prefix)


def print_audit(action: str, details: dict = None, timestamp: bool = True):
    """Print an audit log entry with formatted borders (always shown)."""
    separator = "=" * 80
    ts = f"[{_get_timestamp()}] " if timestamp else ""
    
    # Terminal output with colors and borders
    print(f"\n{Colors.HEADER}{separator}{Colors.ENDC}")
    print(f"{ts}{Colors.BOLD}AUDIT LOG{Colors.ENDC}")
    print(f"{Colors.CYAN}Action:{Colors.ENDC} {action}")
    
    if details:
        for key, value in details.items():
            print(f"{Colors.CYAN}{key}:{Colors.ENDC} {value}")
    
    print(f"{Colors.HEADER}{separator}{Colors.ENDC}\n")
    
    # Log file output (plaintext, multi-line)
    log_lines = [separator, f"AUDIT LOG: {action}"]
    if details:
        for key, value in details.items():
            log_lines.append(f"{key}: {value}")
    log_lines.append(separator)
    
    log_message = "\n".join(log_lines)
    _write_log(LogLevel.AUDIT, log_message, "AUDIT")


def cleanup_old_logs():
    """Delete log files older than 7 days. Called by scheduled task."""
    try:
        log_dir = Path(__file__).parent.parent / "data"
        if not log_dir.exists():
            return
        
        cutoff_date = datetime.now() - timedelta(days=7)
        deleted_count = 0
        
        for log_file in log_dir.glob("*-console.log"):
            try:
                # Parse date from filename (YYYY-MM-DD-console.log)
                date_str = log_file.stem.replace("-console", "")
                file_date = datetime.strptime(date_str, "%Y-%m-%d")
                
                if file_date < cutoff_date:
                    log_file.unlink()
                    deleted_count += 1
            except (ValueError, OSError) as e:
                # Skip files that don't match expected format or can't be deleted
                print_debug(f"Could not process log file {log_file.name}: {e}")
        
        if deleted_count > 0:
            print_info(f"Cleaned up {deleted_count} old log file(s)")
    
    except Exception as e:
        print_error(f"Error during log cleanup: {e}")