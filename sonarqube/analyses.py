from datetime import date

from sonar_qube_api import *

"""
    Map of project versions to analyze. 
    (to skip analyzing a project version delete it from the list)
"""
PROJECTS = {
    "FreeMind": [
        "0.0.3",
        "0.1.0",
        "0.2.0",
        "0.3.1",
        "0.4.0",
        "0.5.0",
        "0.6.0",
        "0.6.1",
        "0.6.5",
        "0.6.7",
        "0.7.1",
        "0.8.0",
        "0.8.1",
        "0.9.0Beta17",
        "0.9.0Beta20",
        "0.9.0RC1",
        "0.9.0RC3",
        "0.9.0RC6",
        "0.9.0RC8",
        "0.9.0RC10",
        "0.9.0RC14",
        "0.9.0",
        "1.0.0Alpha4",
        "1.0.0Alpha6",
        "1.0.0Alpha8",
        "1.0.0Beta2",
        "1.0.0Beta5",
        "1.0.0Beta7",
        "1.0.0Beta9",
        "1.0.0RC1",
        "1.0.0RC3",
        "1.0.0RC4",
        "1.0.0RC5",
        "1.0.0",
        "1.0.1RC1",
        "1.0.1",
        "1.1.0Beta1",
        "1.1.0Beta2",
    ],
    "jEdit": [
        "2.3pre2",
        "2.3pre4",
        "2.3pre6",
        "2.3final",
        "2.4.2",
        "2.5final",
        "2.5.1",
        "2.6final",
        "3.0final",
        "3.0.2",
        "3.1",
        "3.2.2",
        "4.0pre4",
        "4.0",
        "4.0.3",
        "4.1pre5",
        "4.1",
        "4.2pre3",
        "4.2pre8",
        "4.2pre11",
        "4.2",
        "4.3pre1",
        "4.3pre4",
        "4.3pre8",
        "4.3pre9",
        "4.3pre10",
        "4.3pre12",
        "4.3pre13",
        "4.3pre16",
        "4.3pre17",
        "4.3",
        "4.3.2",
        "4.4pre1",
        "4.4.1",
        "4.4.2",
        "4.5.0",
        "4.5.1",
        "4.5.2",
        "5.0.0",
        "5.1.0",
        "5.2pre1",
        "5.2.0",
        "5.3.0",
        "5.4.0",
        "5.5.0",
        "5.6.0",
    ],
    "TuxGuitar": [
        "0.1pre",
        "0.2",
        "0.3",
        "0.3.1",
        "0.4",
        "0.4.1",
        "0.5",
        "0.6",
        "0.7",
        "0.8",
        "0.9",
        "0.9.1",
        "1.0.rc1",
        "1.0.rc2",
        "1.0.rc3",
        "1.0.rc4",
        "1.0",
        "1.1",
        "1.2",
        "1.3.0",
        "1.3.1",
        "1.3.2",
        "1.4",
        "1.5",
        "1.5.1",
        "1.5.2",
        "1.5.3",
        "1.5.4",
    ],
}

"""
    Utility functions
"""


def _group_issues_by_project_analysis(issues, project_analyses):
    """
    Assign issues to project analyses. An issue is assigned to an analysis if it was OPEN at the time of analysis
    (includes issued CREATED during the analysis) or it was CLOSED during that analysis.
    params:
        issues - List of issues in JSON dictionary format
        project_analyses - List of project analyses (software versions)
    return:
        Dictionary of (<project analysis>,[<issue_1>,<issue_2>,...,<issue_k>]) entries
    """
    # Assign issues to project versions, depending on issue status
    # keys are tuples: (<project_name>,<project_version>,<analysis_date>)
    # values are issues represented as JSON dictionaries
    analyses_issues_dict = {}
    MAX_DATE = date(9999, 12, 31)

    for analysis in project_analyses:
        # Initialize an empty list for issues
        analyses_issues_dict[analysis] = []

    for issue in issues:
        for analysis in project_analyses:
            # If issue not for current project we don't care
            if issue.project != analysis.project:
                continue
            # Issue had status OPEN, or was CLOSED during this analysis
            if (
                issue.creationDate
                <= analysis.date
                <= (issue.closeDate if issue.closeDate != None else MAX_DATE)
            ):
                analyses_issues_dict[analysis].append(issue)
    return analyses_issues_dict


"""
    Analysis functions. These produce the output XLS files used to create the article Figures and Table
"""


def export_technical_debt_measures_to_xlsx(
    xlsx_output="./technical_debt_by_software_version.xlsx",
):
    # 1. Get project analyses
    project_names = api_projects_search()
    project_analyses = []

    # SonarQube measures that are also stored
    PROJECT_MEASURES_LIST = [
        "ncloc",
        "classes",
        "statements",
        "functions",
        "development_cost",
        "sqale_debt_ratio",
        "sqale_index",
    ]
    project_measure_history = {}

    for project in project_names:
        project_analyses.extend(api_project_analyses(project))
        project_measure_history[project] = api_measures_search_history(
            project, PROJECT_MEASURES_LIST
        )

    # Sort project analyses by date
    project_analyses.sort(key=lambda x: x.date)

    # 2. Get all recorded issues
    # Must circumvent SonarQube's 10k issue limitation
    issues = api_issues_search(["java"], resolutions=[], types=["CODE_SMELL"])
    issues.extend(api_issues_search(["java"], resolutions=[], types=["BUG"]))
    issues.extend(api_issues_search(["java"], resolutions=[], types=["VULNERABILITY"]))
    print("Total issues returned - " + str(len(issues)))

    # 3. Assign issues to project versions, depending on issue status
    analyses_issues_dict = _group_issues_by_project_analysis(issues, project_analyses)

    # Group technical debt by analysis here
    analyses_technical_debt = {}

    MAX_DATE = date(9999, 12, 31)
    # Dictionary of (<project analysis>,[<issue_1>,<issue_2>,...,<issue_k>]) entries
    for analysis in analyses_issues_dict:
        # This is the list of issues for the given analysis
        analysis_issues = analyses_issues_dict[analysis]

        # <total technical debt> = <new debt> + <existing debt>
        # <fixed technical debt> = issues marked as 'FIXED'
        new_debt = 0
        existing_debt = 0
        fixed_debt = 0

        for issue in analysis_issues:
            issue_close_date = issue.closeDate if issue.closeDate != None else MAX_DATE
            issue_debt = issue.debt if issue.debt != "n/a" else 0

            assert issue.creationDate != issue.closeDate
            if analysis.date == issue.creationDate:
                new_debt += issue_debt
            elif analysis.date == issue_close_date:
                fixed_debt += issue_debt
            else:
                existing_debt += issue_debt

        analyses_technical_debt[analysis] = (new_debt, existing_debt, fixed_debt)

    # 4. Export issues. One sheet per project
    header = [
        "Date",
        "Version",
        "New debt",
        "Existing Debt",
        "Fixed Debt",
    ] + PROJECT_MEASURES_LIST
    book = xlsxwriter.Workbook(xlsx_output)

    for project_name in project_names:
        # Create sheet, write header
        out_sheet = book.add_worksheet(project_name)
        for column in range(len(header)):
            out_sheet.set_column(column, column, 12)
            out_sheet.write(0, column, header[column])
        # Project measures
        project_measures = project_measure_history[project_name]

        row = 1
        for project_analysis in project_analyses:
            if project_analysis.project != project_name:
                continue
            out_sheet.write(row, 0, str(project_analysis.date))
            out_sheet.write(row, 1, project_analysis.version)
            debt_info_tuple = analyses_technical_debt[project_analysis]
            out_sheet.write(row, 2, debt_info_tuple[0])
            out_sheet.write(row, 3, debt_info_tuple[1])
            out_sheet.write(row, 4, debt_info_tuple[2])

            # Write recorded project measures
            for index in range(len(PROJECT_MEASURES_LIST)):
                project_measure = PROJECT_MEASURES_LIST[index]
                for metric in project_measures["measures"]:
                    if metric["metric"] == project_measure:
                        for date_value in metric["history"]:
                            if (
                                sq_datetime_to_date(date_value["date"])
                                == project_analysis.date
                            ):
                                # Once we get the metric and the date right
                                out_sheet.write(row, 5 + index, date_value["value"])
            row += 1
    book.close()


def calculate_package_technical_debt_history():
    for app in PROJECTS:
        book = xlsxwriter.Workbook("Package_TechnicalDebt_History_" + app + ".xlsx")
        header_cell_format = book.add_format(
            {"bold": True, "center_across": True, "bg_color": "#FFFFCC"}
        )

        # Centralizer sheet for maintainability model correlations
        overall_sheet = book.add_worksheet("Package TD History")
        cell_format = book.add_format()
        cell_format.set_num_format("0.00")

        # Dictionary of application versions (key) and associated dict of package TD (value)
        ver_package_td_loc_dict = {}
        # Total TD for a package (across application versions)
        total_package_td_loc_dict = {}

        logger.debug("Application: " + app)
        for project_version in PROJECTS[app]:
            ver_sheet = book.add_worksheet(project_version)
            package_td_loc_dict = {}

            fil_names = api_cu_names(app + "." + project_version)
            print(str(project_version) + " - " + str(len(fil_names)))

            for fil_name in fil_names:
                tech_debt = "n/a"
                ncloc = 0
                component_measure = api_measures_component(
                    fil_name, ["sqale_index", "ncloc"]
                )

                if "component" in component_measure:
                    assert (
                        len(component_measure["component"]["measures"]) == 2
                    ), "Returns sqale_index, ncloc"

                    v0 = component_measure["component"]["measures"][0]
                    v1 = component_measure["component"]["measures"][1]

                    # Sanity checks
                    assert v0["metric"] in [
                        "ncloc",
                        "sqale_index",
                    ], "Must be one of these measurements"
                    assert v1["metric"] in [
                        "ncloc",
                        "sqale_index",
                    ], "Must be one of these measurements"
                    assert v0["metric"] != v1["metric"]

                    if v0["metric"] == "ncloc":
                        ncloc = int(v0["value"])
                        tech_debt = int(v1["value"])
                    else:
                        ncloc = int(v1["value"])
                        tech_debt = int(v0["value"])

                if tech_debt == "n/a":
                    continue

                package_name = fil_name[
                    fil_name.find(":src/") + 5 : fil_name.rfind("/")
                ]
                if not (package_name in package_td_loc_dict):
                    # First item is TD, second is ncloc
                    package_td_loc_dict[package_name] = [0, 0]
                package_td_loc_dict[package_name][0] += tech_debt
                package_td_loc_dict[package_name][1] += ncloc

            # Write to current version sheet
            COLUMN_WIDTHS = [60, 10, 10]
            COLUMN_HEADERS = ["Package", "TD", "LOC"]
            for column in range(len(COLUMN_WIDTHS)):
                ver_sheet.set_column(column, column, COLUMN_WIDTHS[column])
                ver_sheet.write(0, column, COLUMN_HEADERS[column], header_cell_format)

            sorted_package_td_loc_dict = sorted(
                package_td_loc_dict.items(), key=lambda kv: kv[1][0], reverse=True
            )

            row = 1
            for package in sorted_package_td_loc_dict:
                # Package name
                ver_sheet.write(row, 0, package[0])
                # Package TD
                ver_sheet.write(row, 1, package[1][0])
                # PAckage LOC
                ver_sheet.write(row, 2, package[1][1])
                row += 1

            # Record this version's package TD and LOC for overall sheet
            ver_package_td_loc_dict[project_version] = package_td_loc_dict
            # Add current ver package TD and LOC to total
            for package in package_td_loc_dict.keys():
                if not (package in total_package_td_loc_dict):
                    total_package_td_loc_dict[package] = [0, 0]
                total_package_td_loc_dict[package][0] += package_td_loc_dict[package][
                    0
                ]  # TD
                total_package_td_loc_dict[package][1] += package_td_loc_dict[package][
                    1
                ]  # LOC
        # Sort the total package TD before filling in the overall sheet
        sorted_total_package_td_loc_dict = sorted(
            total_package_td_loc_dict.items(), key=lambda kv: kv[1][0], reverse=True
        )

        #
        # Fill in overall package TD
        #
        overall_sheet.write(0, 0, "Package")
        # Write package names sorted descending by total TD on first column
        row = 1
        for package_td_tuple in sorted_total_package_td_loc_dict:
            overall_sheet.write(row, 0, package_td_tuple[0])
            row += 1
        # One version on each subsequent column
        row = 1
        col = 1
        ver_list = sorted(list(ver_package_td_loc_dict.keys()))

        for ver in ver_list:
            overall_sheet.write(0, col, ver)
            for package_tuple in sorted_total_package_td_loc_dict:
                # Not all packages appear in all application versions
                if package_tuple[0] not in ver_package_td_loc_dict[ver].keys():
                    # overall_sheet.write(row, col, 0)
                    pass
                else:
                    # Only write TD for those app version/package combos that contain source code
                    if ver_package_td_loc_dict[ver][package_tuple[0]][1] > 0:
                        overall_sheet.write(
                            row, col, ver_package_td_loc_dict[ver][package_tuple[0]][0]
                        )
                row += 1
            row = 1
            col += 1

        #
        # Fill in overall package LOC
        #
        start_row = len(sorted_total_package_td_loc_dict) + 5
        row = start_row
        # Write package names sorted descending by total TD on first column
        for package_td_tuple in sorted_total_package_td_loc_dict:
            overall_sheet.write(row, 0, package_td_tuple[0])
            row += 1
        # One version on each subsequent column
        row = start_row
        col = 1
        ver_list = sorted(list(ver_package_td_loc_dict.keys()))

        for ver in ver_list:
            overall_sheet.write(row - 1, col, ver)
            for package_tuple in sorted_total_package_td_loc_dict:
                # Not all packages appear in all application versions
                if package_tuple[0] not in ver_package_td_loc_dict[ver].keys():
                    # overall_sheet.write(row, col, 0)
                    pass
                else:
                    val = ver_package_td_loc_dict[ver][package_tuple[0]][1]
                    if val != 0:
                        overall_sheet.write(row, col, val)
                row += 1
            row = start_row
            col += 1

        book.close()


def export_detailed_td_characterization_by_software_version_xlsx():
    # 1. Get project analyses
    project_analyses = {}
    for project in api_projects_search():
        project_analyses[project] = api_project_analyses(project)
        # Sort project analyses by date
        project_analyses[project].sort(key=lambda x: x.date)

    # 2. Get all recorded Java issues
    # Must circumvent SonarQube's 10k issue limitation
    issues = api_issues_search(["java"], resolutions=[], types=["CODE_SMELL"])
    issues.extend(api_issues_search(["java"], resolutions=[], types=["BUG"]))
    issues.extend(api_issues_search(["java"], resolutions=[], types=["VULNERABILITY"]))
    print("Total issues returned - " + str(len(issues)))

    # 3. Assign issues to project versions, depending on issue status
    # Dictionary of (<project analysis>,[<issue_1>,<issue_2>,...,<issue_k>]) entries
    all_analyses = []
    for value in project_analyses.values():
        all_analyses.extend(value)
    analyses_issues_dict = _group_issues_by_project_analysis(issues, all_analyses)

    # 4. Export issues grouped by file. One XSLX per project, one sheet per software version
    for project_name in project_analyses:
        logger.debug(
            "Aggregate technical debt at file level in each software version for project - "
            + project_name
        )
        work_book = xlsxwriter.Workbook(
            "technical_debt_by_software_version_and_file_" + project_name + ".xlsx"
        )
        header_cell_format = work_book.add_format(
            {"bold": True, "center_across": True, "bg_color": "#FFFFCC"}
        )

        overall_sheet = work_book.add_worksheet("Overall")
        overall_sheet_col = 1
        # List of per-quintile technical debt
        quintile_info = []

        overall_sheet.write(0, 0, "version")
        overall_sheet.write(1, 0, "Q1 (file)")
        overall_sheet.write(2, 0, "Q2 (file)")
        overall_sheet.write(3, 0, "Q3 (file)")
        overall_sheet.write(4, 0, "Q4 (file)")
        overall_sheet.write(5, 0, "Q5 (file)")
        overall_sheet.write(6, 0, "CORREL")

        overall_sheet.write(8, 0, "BLOCKER")
        overall_sheet.write(9, 0, "CRITICAL")
        overall_sheet.write(10, 0, "MAJOR")
        overall_sheet.write(11, 0, "MINOR")
        overall_sheet.write(12, 0, "INFO")

        overall_sheet.write(14, 0, "BUG")
        overall_sheet.write(15, 0, "VULNERABILITY")
        overall_sheet.write(16, 0, "CODE SMELL")

        # Technical debt in this software version
        # a. Calculated at tag level
        software_version_td_tag_level = {}
        # b. Calculated at rule level
        software_version_td_rule_level = {}

        for current_analysis in project_analyses[project_name]:
            # Create an entry for this version in the td dictionary
            software_version_td_tag_level[current_analysis] = {}
            software_version_td_rule_level[current_analysis] = {}

            logger.debug("Analyzing - " + current_analysis.version)
            project_sheet = work_book.add_worksheet(current_analysis.version)
            project_sheet.set_column(0, 0, 80)
            project_sheet.set_column(9, 9, 12)
            project_sheet.set_column(10, 10, 12)
            project_sheet.write(0, 0, "component", header_cell_format)
            project_sheet.write(0, 1, "debt", header_cell_format)
            project_sheet.write(0, 2, "LOC", header_cell_format)
            project_sheet.write(0, 3, "Blocker", header_cell_format)
            project_sheet.write(0, 4, "Critical", header_cell_format)
            project_sheet.write(0, 5, "Major", header_cell_format)
            project_sheet.write(0, 6, "Minor", header_cell_format)
            project_sheet.write(0, 7, "Info", header_cell_format)
            project_sheet.write(0, 8, "Bug", header_cell_format)
            project_sheet.write(0, 9, "Code Smell", header_cell_format)
            project_sheet.write(0, 10, "Vulnerability", header_cell_format)

            # Dictionary of file-level technical debt
            component_td = {}
            for issue in analyses_issues_dict[current_analysis]:
                # We don't care about FIXED issues
                if issue.closeDate == current_analysis.date:
                    continue

                # Issue debt per component
                issue_debt = issue.debt if issue.debt != "n/a" else 0

                # Not interested in file-level breakdown
                # a. Record technical debt by tag at issue level
                issue_tags = issue.tags.split(",") if len(issue.tags) > 2 else []
                for tag in issue_tags:
                    if tag not in software_version_td_tag_level[current_analysis]:
                        software_version_td_tag_level[current_analysis][tag] = 0
                    software_version_td_tag_level[current_analysis][
                        tag
                    ] += issue_debt / len(issue_tags)

                # b. Record technical debt by rule at issue level
                if issue.rule not in software_version_td_rule_level[current_analysis]:
                    software_version_td_rule_level[current_analysis][issue.rule] = 0
                software_version_td_rule_level[current_analysis][
                    issue.rule
                ] += issue_debt

                if issue.component not in component_td:
                    component_td[issue.component] = {
                        "TD": 0,
                        "BUG": 0,
                        "CODE_SMELL": 0,
                        "VULNERABILITY": 0,
                        "BLOCKER": 0,
                        "CRITICAL": 0,
                        "MAJOR": 0,
                        "MINOR": 0,
                        "INFO": 0,
                    }
                component_td[issue.component][str(issue.severity)] += issue_debt
                component_td[issue.component][str(issue.type)] += issue_debt
                component_td[issue.component]["TD"] += issue_debt

            # Sort components by technical debt using a list
            components = []
            for comp in component_td:
                components.append((comp, component_td[comp]))
            components.sort(key=lambda x: x[1]["TD"], reverse=True)

            row = 1
            for tup in components:
                # Sanity checks
                assert (
                    tup[1]["TD"]
                    == tup[1]["BUG"] + tup[1]["CODE_SMELL"] + tup[1]["VULNERABILITY"]
                )
                assert (
                    tup[1]["TD"]
                    == tup[1]["BLOCKER"]
                    + tup[1]["CRITICAL"]
                    + tup[1]["MAJOR"]
                    + tup[1]["MINOR"]
                    + tup[1]["INFO"]
                )

                # One file / its TD on every line
                # Leave out project name and src/; e.g. "FreeMind:src/"
                file_name = tup[0][tup[0].index("src") :]
                project_sheet.write(row, 0, file_name)
                project_sheet.write(row, 1, tup[1]["TD"])
                # Column 2 is LOC and is handled below
                project_sheet.write(row, 3, tup[1]["BLOCKER"])
                project_sheet.write(row, 4, tup[1]["CRITICAL"])
                project_sheet.write(row, 5, tup[1]["MAJOR"])
                project_sheet.write(row, 6, tup[1]["MINOR"])
                project_sheet.write(row, 7, tup[1]["INFO"])
                project_sheet.write(row, 8, tup[1]["BUG"])
                project_sheet.write(row, 9, tup[1]["CODE_SMELL"])
                project_sheet.write(row, 10, tup[1]["VULNERABILITY"])

                # We hit the SonarQube instance with individual projects for ncloc information
                # (this is not kept for previous versions of the project)
                component_id = (
                    project_name + "." + current_analysis.version + ":" + file_name
                )
                res = requests.get(
                    SONAR_SERVER_SINGLE_URL + "/api/measures/component",
                    auth=HTTPBasicAuth("admin", "Parola123456789!"),
                    params={
                        "component": component_id,
                        "metricKeys": "ncloc,sqale_index",
                    },
                ).json()

                # Certain files cannot be found, as they are renamed/moved in newer versions, but this information
                # is not persisted for the older project versions in the history

                if "errors" in res:
                    logger.debug("error " + res["errors"][0]["msg"])
                    project_sheet.write(row, 2, "n/a")
                else:
                    project_sheet.write(
                        row, 2, int(res["component"]["measures"][0]["value"])
                    )
                row += 1

            # Quintiles!
            step = len(components) // 5
            q1 = components[:step]
            q2 = components[step : 2 * step]
            q3 = components[2 * step : 3 * step]
            q4 = components[3 * step : 4 * step]
            q5 = components[4 * step :]
            assert len(components) == len(q1) + len(q2) + len(q3) + len(q4) + len(q5)

            overall_sheet.write(0, overall_sheet_col, current_analysis.version)
            overall_sheet.write(1, overall_sheet_col, sum(x[1]["TD"] for x in q1))
            overall_sheet.write(2, overall_sheet_col, sum(x[1]["TD"] for x in q2))
            overall_sheet.write(3, overall_sheet_col, sum(x[1]["TD"] for x in q3))
            overall_sheet.write(4, overall_sheet_col, sum(x[1]["TD"] for x in q4))
            overall_sheet.write(5, overall_sheet_col, sum(x[1]["TD"] for x in q5))

            # Excel CORREL formula. e.g. '=CORREL('0.1pre'!B2:B10,'0.1pre'!C2:C10)'
            correl_formula = (
                "=CORREL('"
                + current_analysis.version
                + "'!B2:B"
                + str(row)
                + ",'"
                + current_analysis.version
                + "'!C2:C"
                + str(row)
                + ")"
            )
            overall_sheet.write(6, overall_sheet_col, correl_formula)

            # Technical debt broken down by severity / type
            overall_sheet.write(
                8, overall_sheet_col, sum(x[1]["BLOCKER"] for x in components)
            )
            overall_sheet.write(
                9, overall_sheet_col, sum(x[1]["CRITICAL"] for x in components)
            )
            overall_sheet.write(
                10, overall_sheet_col, sum(x[1]["MAJOR"] for x in components)
            )
            overall_sheet.write(
                11, overall_sheet_col, sum(x[1]["MINOR"] for x in components)
            )
            overall_sheet.write(
                12, overall_sheet_col, sum(x[1]["INFO"] for x in components)
            )

            overall_sheet.write(
                14, overall_sheet_col, sum(x[1]["BUG"] for x in components)
            )
            overall_sheet.write(
                15, overall_sheet_col, sum(x[1]["VULNERABILITY"] for x in components)
            )
            overall_sheet.write(
                16, overall_sheet_col, sum(x[1]["CODE_SMELL"] for x in components)
            )
            overall_sheet_col += 1

        # a. Technical debt broken down at tag level
        # We need analysis of all software versions to order tags by incurred debt
        tag_dict = {}
        for project_analysis in software_version_td_tag_level:
            for tag in software_version_td_tag_level[project_analysis]:
                if tag not in tag_dict:
                    tag_dict[tag] = 0
                tag_dict[tag] += software_version_td_tag_level[project_analysis][tag]
        tag_list = list(tag_dict.keys())
        tag_list.sort(key=lambda x: tag_dict[x], reverse=True)

        # Write tag names
        row = 18
        for tag in tag_list:
            overall_sheet.write(row, 0, tag)
            row += 1

        # Write TD for each tag per software version
        col = 1
        for project_analysis in software_version_td_tag_level:
            row = 18
            for tag in tag_list:
                if tag not in software_version_td_tag_level[project_analysis]:
                    overall_sheet.write(row, col, 0)
                else:
                    overall_sheet.write(
                        row,
                        col,
                        int(software_version_td_tag_level[project_analysis][tag]),
                    )
                row += 1
            col += 1

        # b. Technical debt broken down at rule level
        rule_dict = {}
        for project_analysis in software_version_td_rule_level:
            for rule in software_version_td_rule_level[project_analysis]:
                if rule not in rule_dict:
                    rule_dict[rule] = 0
                rule_dict[rule] += software_version_td_rule_level[project_analysis][
                    rule
                ]
        rule_list = list(rule_dict.keys())
        rule_list.sort(key=lambda x: rule_dict[x], reverse=True)

        # Write rule identifiers
        row = 18 + len(tag_list) + 1
        for rule in rule_list:
            overall_sheet.write(row, 0, rule)
            row += 1

        # Write TD for each rule per software version
        col = 1
        for project_analysis in software_version_td_rule_level:
            row = 18 + len(tag_list) + 1
            for rule in rule_list:
                if rule not in software_version_td_rule_level[project_analysis]:
                    overall_sheet.write(row, col, 0)
                else:
                    overall_sheet.write(
                        row,
                        col,
                        int(software_version_td_rule_level[project_analysis][rule]),
                    )
                row += 1
            col += 1

        # c. Technical debt quartiles by rules
        # do 20% of rules generate 80% of technical debt?
        row = 18 + len(tag_list) + len(rule_list) + 2
        overall_sheet.write(row, 0, "Q1 (rule)")
        overall_sheet.write(row + 1, 0, "Q2 (rule)")
        overall_sheet.write(row + 2, 0, "Q3 (rule)")
        overall_sheet.write(row + 3, 0, "Q4 (rule)")
        overall_sheet.write(row + 4, 0, "Q5 (rule)")

        col = 1
        for project_analysis in software_version_td_rule_level:
            rules_debt_dict = software_version_td_rule_level[project_analysis]
            rules_debt_filtered_dict = {
                k: v for k, v in rules_debt_dict.items() if v > 0
            }
            rules_debt_list = [(k, v) for k, v in rules_debt_filtered_dict.items()]
            rules_debt_list.sort(key=lambda x: x[1], reverse=True)
            step = len(rules_debt_list) // 5

            q1 = rules_debt_list[:step]
            q2 = rules_debt_list[step : 2 * step]
            q3 = rules_debt_list[2 * step : 3 * step]
            q4 = rules_debt_list[3 * step : 4 * step]
            q5 = rules_debt_list[4 * step :]
            assert len(rules_debt_list) == len(q1) + len(q2) + len(q3) + len(q4) + len(
                q5
            )

            overall_sheet.write(row, col, sum(x[1] for x in q1))
            overall_sheet.write(row + 1, col, sum(x[1] for x in q2))
            overall_sheet.write(row + 2, col, sum(x[1] for x in q3))
            overall_sheet.write(row + 3, col, sum(x[1] for x in q4))
            overall_sheet.write(row + 4, col, sum(x[1] for x in q5))
            col += 1

        work_book.close()


if __name__ == "__main__":
    """
    Calculate technical debt ratios by application version and export to 'technical_debt_by_software_version.xlxs'
    """
    # export_technical_debt_measures_to_xlsx()

    """
    Calculate technical debt at tag and rule levels per application version
    """
    # export_detailed_td_characterization_by_software_version_xlsx()

    """
    Calculate technical debt at package level and correlate it with package LOC
    """
    # calculate_package_technical_debt_history()
