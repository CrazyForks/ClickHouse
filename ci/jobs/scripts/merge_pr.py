import json
import sys
import traceback
from dataclasses import dataclass
from typing import List, Optional

sys.path.append("./")

from ci.praktika.gh import GH
from ci.praktika.result import Result
from ci.praktika.utils import Shell


class CheckStatuses:
    PR = "PR"
    CH_INC_SYNC = "CH Inc sync"
    MERGEABLE_CHECK = "Mergeable Check"


@dataclass
class CommitStatus:
    state: str
    description: str
    url: str
    context: str


class UserSelector:
    def get_user_choice_from_menu(menuitems, question="Enter your choice"):
        menu_map = {}
        for i, item in enumerate(menuitems, start=1):
            menu_map[i] = item
            val = item[0] if isinstance(item, tuple) else item
            print(f"{i}. {val}")

        while True:
            try:
                choice = input(f"\n{question} (1-{len(menuitems)}): ")
                choice_num = int(choice)

                if 1 <= choice_num <= len(menuitems):
                    selected_item = menu_map[choice_num]
                    break
                else:
                    print("Invalid choice. Please enter a number between 1 and 3.")
            except ValueError:
                print("Invalid input. Please enter a number.")
            except KeyboardInterrupt:
                print("\n\nSelection cancelled.")
                return

        return selected_item

    def get_user_numberic_input(question="Enter a number", validator=lambda x: True):
        while True:
            try:
                choice = input(f"\n{question}: ")
                choice_num = int(choice)
                if validator(choice_num):
                    break
                else:
                    raise ValueError("Invalid input. Please enter a number.")
            except ValueError:
                print("Invalid input. Please enter a number.")
            except KeyboardInterrupt:
                print("\n\nSelection cancelled.")
                return
        return choice_num

    def get_yes_or_no_answer(question="Do you want to proceed?"):
        while True:
            try:
                choice = input(f"\n{question} (y/n): ")
                if choice.lower() in ("y", "yes"):
                    return True
                elif choice.lower() in ("n", "no"):
                    return False
                else:
                    print("Invalid choice. Please enter 'y' or 'n'.")
            except KeyboardInterrupt:
                print("\n\nSelection cancelled.")
                return


@dataclass
class CIGHIssue:
    title: str
    url: str
    labels: List[str]


class JobTypes:
    STATELESS = "Stateless"
    INTEGRATION = "Integration"
    AST_FUZZER = "AST Fuzzer"
    BUILD = "Build"
    FORMATTER = "Formatter"
    BUZZ_FUZZER = "Buzz"


@dataclass
class CIFailure:
    job_name: str
    job_status: str
    test_name: str
    test_status: str
    test_info: str
    praktika_result: Result
    issue: Optional[CIGHIssue] = None
    job_type: str = ""
    ignorable: bool = False

    def __post_init__(self):
        if "Stateless" in self.job_name:
            self.job_type = JobTypes.STATELESS
        elif "Integration" in self.job_name:
            self.job_type = JobTypes.INTEGRATION
        elif "AST" in self.job_name:
            self.job_type = JobTypes.AST_FUZZER
        elif "formatter" in self.job_name:
            self.job_type = JobTypes.FORMATTER
            self.ignorable = True
        elif "Buzz" in self.job_name:
            self.job_type = JobTypes.BUZZ_FUZZER
            self.ignorable = True
            self.praktika_result.get_hlabel_link("pr")
        else:
            raise Exception(f"Unknown job type for job name: {self.job_name}")
        self.issue_url = self.praktika_result.get_hlabel_link("flaky") or ""

    def __repr__(self):
        res = self.job_name + ":\n"
        res += f"  - {self.test_status}: {self.test_name}\n"
        if self.issue_url:
            res += f"   has issue: {self.issue_url}\n"
        return res


class JobResultProcessor:

    @staticmethod
    def process_job_result(job_result: Result):
        print(f"Job {job_result.name} status is {job_result.status}")
        if "Stateless" in job_result.name:
            JobResultProcessor.process_stateless_job(job_result)
        elif "Integration" in job_result.name:
            JobResultProcessor.process_integration_job(job_result)
        elif "AST" in job_result.name:
            JobResultProcessor.process_ast_fuzzer_job(job_result)
        else:
            raise Exception(f"Unknown job type: {job_result.name}")

    @staticmethod
    def process_stateless_job(job_result: Result):
        print(f"Failed tests:")
        for test in job_result.results:
            print(
                test.to_stdout_formatted(truncate_from_top=False, max_info_lines_cnt=20)
            )

    @staticmethod
    def process_integration_job(job_result: Result):
        print(f"Failed tests:")
        for test in job_result.results:
            print(
                test.to_stdout_formatted(truncate_from_top=False, max_info_lines_cnt=20)
            )

    @staticmethod
    def process_ast_fuzzer_job(job_result: Result):
        assert False, "TODO"

    @staticmethod
    def get_pr_result(commit_status_data: CommitStatus, pr_number, commit_sha):
        if commit_status_data.state not in (
            Result.Status.SUCCESS,
            Result.Status.FAILED,
        ):
            raise Exception(
                f"Status for {commit_status_data.context} is not completed: {commit_status_data.state} - cannot proceed"
            )
        report_url = f"https://s3.amazonaws.com/clickhouse-test-reports/PRs/{pr_number}/{commit_sha}/result_pr.json"
        _ = Shell.check(f"curl {report_url} -o /tmp/result_pr.json > /dev/null 2>&1")
        pr_result = Result.from_file("/tmp/result_pr.json")
        return pr_result

    @staticmethod
    def collect_all_failures(pr_result, failures):
        success_job_cnt = 0
        failed_job_cnt = 0
        skipped_job_cnt = 0
        dropped_job_cnt = 0
        for job_result in pr_result.results:
            if job_result.is_success():
                success_job_cnt += 1
            elif job_result.is_failure():
                failed_job_cnt += 1
            elif job_result.is_skipped():
                skipped_job_cnt += 1
            elif job_result.is_dropped():
                dropped_job_cnt += 1
            else:
                raise Exception(f"Unknown job result status: {job_result.status}")
        assert (
            success_job_cnt + failed_job_cnt + skipped_job_cnt + dropped_job_cnt
            == len(pr_result.results)
        )
        if pr_result.is_ok():
            print(f"All jobs are successful - ready to merge")
        else:
            print(f"Not all jobs are successful - proceed with caution")
            for job_result in pr_result.results:
                if not job_result.is_ok():
                    if job_result.results:
                        for test_result in job_result.results:
                            failures.append(
                                CIFailure(
                                    job_name=job_result.name,
                                    job_status=job_result.status,
                                    test_name=test_result.name,
                                    test_status=test_result.status,
                                    test_info=test_result.info,
                                    praktika_result=test_result,
                                )
                            )
                    else:
                        failures.append(
                            CIFailure(
                                job_name=job_result.name,
                                job_status=job_result.status,
                                test_name="",
                                test_status="",
                                test_info=job_result.info,
                                praktika_result=job_result,
                            )
                        )

    @staticmethod
    def process_sync_status(commit_status_data: CommitStatus, sha: str):
        if commit_status_data.state in (Result.Status.SUCCESS,):
            pass
        elif commit_status_data.state in (Result.Status.FAILED,):
            print(f"\nCH Sync failed for commit {commit_status_data.context}")
            if UserSelector.get_yes_or_no_answer("You sure it can be ignored?"):
                GH.post_commit_status(
                    commit_status_data.context,
                    Result.Status.SUCCESS,
                    "Ignored",
                    commit_status_data.url,
                    sha=sha,
                    repo="ClickHouse/ClickHouse",
                )
            else:
                sys.exit(0)
        elif commit_status_data.state in (Result.Status.PENDING,):
            if commit_status_data.description == "tests started":
                print(
                    f"\n{commit_status_data.context} is pending with description {commit_status_data.description}"
                )
                if UserSelector.get_yes_or_no_answer("You sure it can be ignored?"):
                    GH.post_commit_status(
                        commit_status_data.context,
                        Result.Status.SUCCESS,
                        "Ignored",
                        commit_status_data.url,
                        sha=sha,
                        repo="ClickHouse/ClickHouse",
                    )
                else:
                    sys.exit(0)
            else:
                print(
                    f"CH Sync commit status state: {commit_status_data.state} and description: {commit_status_data.description} - cannot proceed"
                )
                sys.exit(0)


if __name__ == "__main__":
    my_prs_number_and_title = Shell.get_output(
        "gh pr list --author @me --json number,title --base master --limit 20"
    )
    my_prs_number_and_title = json.loads(my_prs_number_and_title)
    pr_menu = []
    pr_menu.append((f"Enter PR number manually", 0))
    for pr_dict in my_prs_number_and_title:
        pr_number = pr_dict["number"]
        pr_title = pr_dict["title"]
        pr_menu.append((f"#{pr_number}: {pr_title}", pr_number))

    selected_pr = UserSelector.get_user_choice_from_menu(
        pr_menu, "Select a PR to merge"
    )
    if selected_pr[1] == 0:
        pr_number = UserSelector.get_user_numberic_input(
            "Enter PR number", lambda x: x > 80000 and x < 100000
        )
    else:
        pr_number = selected_pr[1]

    pr_url = f"https://github.com/ClickHouse/ClickHouse/pull/{pr_number}"
    print(f"\nSelected PR: {selected_pr[0]}")
    print(f"PR URL: {pr_url}")

    # Get the head commit SHA
    pr_data = Shell.get_output(f"gh pr view {pr_number} --json headRefOid,headRefName")
    pr_data = json.loads(pr_data)
    head_sha = pr_data["headRefOid"]
    print(f"Head commit SHA: {head_sha}")

    # Get commit statuses with pagination
    statuses_list = Shell.get_output(
        f"gh api repos/ClickHouse/ClickHouse/commits/{head_sha}/statuses --paginate"
    )
    statuses_list = json.loads(statuses_list)

    # Filter for specific statuses (take first match for each)
    required_checks = [
        CheckStatuses.PR,
        CheckStatuses.CH_INC_SYNC,
        CheckStatuses.MERGEABLE_CHECK,
    ]
    status_map = {}

    for status in statuses_list:
        context = status["context"]
        if context in required_checks and context not in status_map:
            status_map[context] = CommitStatus(
                state=status["state"],
                description=status.get("description", "N/A"),
                url=status.get("target_url", ""),
                context=context,
            )

    sync_status = status_map.get(CheckStatuses.CH_INC_SYNC)

    print(f"\nCommit statuses:")
    for check in required_checks:
        if check in status_map:
            state = status_map[check].state
            desc = status_map[check].description
            print(f"  - {check}: {state} - {desc}")
        else:
            print(f"  - {check}: unknown")
    print("")

    CI_FAILURES = []
    pr_result = JobResultProcessor.get_pr_result(
        status_map[CheckStatuses.PR], pr_number, head_sha
    )
    JobResultProcessor.collect_all_failures(
        pr_result,
        failures=CI_FAILURES,
    )

    print("\nCI failures:")
    known_failures = [f for f in CI_FAILURES if f.issue_url]
    unknown_ignorable_failures = [
        f for f in CI_FAILURES if not f.issue_url and f.ignorable
    ]
    unknown_failures = [f for f in CI_FAILURES if not f.issue_url and not f.ignorable]
    if known_failures:
        print("--- Known problems ---")
        for failure in known_failures:
            print(failure)

    if unknown_ignorable_failures:
        print("--- Unknown ignorable problems ---")
        for failure in unknown_ignorable_failures:
            print(failure)

    if unknown_failures:
        print("--- Unknown problems ---")
        for failure in unknown_failures:
            print(failure)

        if not UserSelector.get_yes_or_no_answer(
            "Do you want to create issue for any of unknown problems?"
        ):
            sys.exit(0)

        print("Thank you for your time!")

    if unknown_failures:
        if not UserSelector.get_yes_or_no_answer(
            "Do you want to create issue for any of unknown problems?"
        ):
            sys.exit(0)
        else:
            assert False, "Not implemented"

    if not unknown_failures:
        if unknown_ignorable_failures:
            question = f"Do you want to merge PR ignoring {len(unknown_ignorable_failures)} unknown ignorable problem(s)?"
        else:
            question = "All checks passed. Do you want to merge the PR?"
        if not UserSelector.get_yes_or_no_answer(question):
            sys.exit(0)

    if unknown_ignorable_failures:
        for failure in unknown_ignorable_failures:
            failure.praktika_result.set_comment("IGNORED")
        try:
            print("Updating CI summary in the PR comment")
            summary_body = GH.ResultSummaryForGH.from_result(
                pr_result,
                sha=head_sha,
            ).to_markdown(pr_number, head_sha, workflow_name="PR", branch="")
            if not GH.post_updateable_comment(
                comment_tags_and_bodies={"summary": summary_body},
                pr=pr_number,
                repo="ClickHouse/ClickHouse",
                only_update=True,
                verbose=False,
            ):
                print(f"ERROR: failed to post CI summary")
            # reset unknown ignorable failures
            unknown_ignorable_failures = []
        except Exception as e:
            print(f"ERROR: failed to post CI summary, ex: {e}")
            traceback.print_exc()

    JobResultProcessor.process_sync_status(sync_status, sha=head_sha)

    if not unknown_ignorable_failures:
        if Shell.check(f"gh pr merge {pr_number} --auto"):
            print(f"PR {pr_number} auto merge has been enabled")
