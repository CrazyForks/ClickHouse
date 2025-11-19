import re
from pathlib import Path


class StackTraceReader(object):

    @staticmethod
    def get_stack_trace(file_path=None, stderr=None, max_lines=1000):
        lines = []
        stack_trace_pattern = re.compile(r"<Fatal> BaseDaemon: \d{1,2}\. ")
        if file_path:
            assert Path(file_path).is_file(), f"File {file_path} does not exist"
            with open(file_path, "r", errors="replace") as file:
                all_lines = file.readlines()
        elif stderr:
            all_lines = stderr.split("\n")
        else:
            raise Exception("Either file_path or stderr must be provided")

        # Only process last max_lines lines
        last_lines = all_lines[-max_lines:] if len(all_lines) > max_lines else all_lines

        # Read backwards from the end
        for line in reversed(last_lines):
            if "<Fatal> BaseDaemon: Stack trace:" in line:
                break
            # Only keep lines that match the stack trace pattern
            match = stack_trace_pattern.search(line)
            if match:
                # Extract only the part after the pattern
                extracted = line[match.end() :]
                # Remove everything before and including 'ClickHouse/' if present
                if "ClickHouse/" in extracted:
                    extracted = extracted.split("ClickHouse/")[1]
                lines.append(extracted)
            else:
                lines.append(line)
        # Reverse to get original order
        lines.reverse()
        lines = [line.strip().replace("\n", "") for line in lines]
        return "\n".join(lines) if lines else None

    @staticmethod
    def get_fatal_error(stderr=None):
        if not stderr:
            return ""

        lines = stderr.split("\n")
        result = []
        in_error = False

        for line in lines:
            if "Logical error:" in line:
                in_error = True
                # Extract the part starting from "Logical error:"
                error_start = line.find("Logical error:")
                result.append(line[error_start:])
            elif in_error:
                # Stop if we hit a line starting with '['
                if line.strip().startswith("["):
                    break
                # Continue collecting lines that are part of the error
                if line.strip():
                    result.append(line)

        return "\n".join(result) if result else ""

    @staticmethod
    def get_fuzzer_query(fuzzer_log, max_lines=200):
        assert Path(fuzzer_log).is_file(), f"File {fuzzer_log} does not exist"

        with open(fuzzer_log, "r", errors="replace") as file:
            all_lines = file.readlines()

        # Only process last max_lines lines
        last_lines = all_lines[-max_lines:] if len(all_lines) > max_lines else all_lines

        # Read backwards to find the last line that starts with SELECT
        sql_keywords = (
            "SELECT",
            "INSERT",
            "UPDATE",
            "DELETE",
            "CREATE",
            "DROP",
            "ALTER",
            "TRUNCATE",
            "WITH",
        )
        for line in reversed(last_lines):
            stripped = line.strip()
            if any(stripped.startswith(keyword) for keyword in sql_keywords):
                return stripped
        return None


if __name__ == "__main__":
    # test
    test_file = "fatal.log"
    print(StackTraceReader.get_stack_trace(test_file))
