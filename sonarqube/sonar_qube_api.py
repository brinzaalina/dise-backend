import logging
import requests
import xlsxwriter
import enum
from datetime import date
from requests.auth import HTTPBasicAuth

"""
    Set up logger format
"""
logger = logging.getLogger("metrics")
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler("metrics.log")
fh.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)

formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
fh.setFormatter(formatter)
ch.setFormatter(formatter)
logger.addHandler(fh)
logger.addHandler(ch)

"""
    Constants
"""
METRIC_TYPES = ["Project", "FileType", "Module", "Package", "Interface", "Class"]

"""
    SonarQube API endpoints
"""
METRIC_SEARCH_URL = "/api/metrics/search"
PROJECT_SEARCH_URL = "/api/projects/search"
PROJECT_METRIC_URL = "/api/measures/component"
ISSUES_SEARCH = "/api/issues/search"

"""
    SonarQube API ports
"""
# Server where historical analysis results are stored
SONAR_SERVER_HISTORY_URL = "http://localhost:9000"

# Server where each project version was analyzed independently
SONAR_SERVER_SINGLE_URL = "http://localhost:9100"

"""
    Helper functions
"""


def param_list_to_strings(data):
    """
    data = ['a', 'b', 'c'] -> a,b,c
    """
    result = ""
    for d in data:
        result += str(d)
        result += ","
    return result[:-1]


def sq_datetime_to_date(sq_datetime):
    """
    Convert SonarQube date/time string to a native Python date
    params:
        sq_datetime - SonarQube date_time (e.g. "2013-10-16T00:00:00+0300")
    output:
        Python date objects(e.g. date(2013, 10, 16) for the example above)
    """
    # return date(int(sq_datetime[:4]), int(sq_datetime[5:7]), int(sq_datetime[8:10]))
    return date.fromisoformat(sq_datetime[:10])


def sq_duration_to_minutes(sq_duration):
    """
    Convert SonarQube time duration to minutes.
    e.g. 35min -> 35, 1h25min -> 85, 4h30min -> 270, 1d1h10min -> 550
    params:
        sq_duration - Duration represented as string
    output:
        int value in minutes
    """
    if sq_duration == "n/a":
        return "n/a"
    # Determine days
    d_index = sq_duration.find("d")
    days = int(sq_duration[:d_index]) if d_index > -1 else 0
    sq_duration = sq_duration[d_index + 1 :]
    # Determine hours
    h_index = sq_duration.find("h")
    hours = int(sq_duration[:h_index]) if h_index > -1 else 0
    sq_duration = sq_duration[h_index + 1 :]
    # Determine minutes
    min_index = sq_duration.find("min")
    if min_index == -1:
        return days * 480 + hours * 60 + int(sq_duration[:min_index])
    return days * 480 + hours * 60 + int(sq_duration[:min_index])


def set_issue_lifetime(issue, project_analyses):
    """
    Calculate the issue's lifetime (number of versions until fixed)
    Stored in the new issue.lifetime field (0 - if issue.resolution is not FIXED)
    input:
        issue - the issue itself
        project_analyses - the list of project analyses sorted increasing by date
    output:
        issue.lifetime (new object attribute)
    NB! issue.lifetime = 0 for unresolved issues
    """
    if issue.resolution == None:
        issue.lifetime = 0
        return

    created_index = -1
    closed_index = -1
    for index in range(len(project_analyses)):
        if project_analyses[index].date == issue.creationDate:
            created_index = index
        if project_analyses[index].date == issue.closeDate:
            closed_index = index
            break
    assert -1 < created_index < closed_index < len(project_analyses)
    issue.lifetime = closed_index - created_index


"""
    SonarQube API helper classes
"""


class Resolution(enum.Enum):
    FIXED = 0

    def __str__(self):
        return self.name


class Status(enum.Enum):
    CLOSED = 0
    OPEN = 1

    def __str__(self):
        return self.name


class Severity(enum.Enum):
    INFO = 0
    MINOR = 1
    MAJOR = 2
    CRITICAL = 3
    BLOCKER = 4

    def __str__(self):
        return self.name


class Type(enum.Enum):
    CODE_SMELL = 0
    BUG = 1
    VULNERABILITY = 2

    def __str__(self):
        return self.name


class Issue:
    """
    Represents a SonarQube issue
    """

    def __init__(self, json_data):
        self.key = json_data["key"]
        self.rule = json_data["rule"]
        self.json = json_data
        self.hash = json_data["hash"] if "hash" in json_data else "n/a"
        self.message = json_data["message"]
        column_index = json_data["component"].index(":")
        self.project = json_data["component"][:column_index]
        self.component = json_data["component"][column_index + 1 :]

        # Issue resolution, key is missing if issue is not resolved
        if "resolution" in json_data:
            # Resolutions is either FIXED or not existing
            assert json_data["resolution"] == "FIXED"
        self.resolution = (
            Resolution.FIXED
            if ("resolution" in json_data) and (json_data["resolution"] == "FIXED")
            else None
        )

        # Issue status, OPEN or CLOSED for now
        assert json_data["status"] in [
            "OPEN",
            "CLOSED",
        ], "We do not yet support issues not either OPEN or CLOSED"
        self.status = Status.CLOSED if json_data["status"] == "CLOSED" else Status.OPEN

        self.creationDate = sq_datetime_to_date(
            json_data["creationDate"]
        )  # issue must have a creation date
        self.updateDate = (
            sq_datetime_to_date(json_data["updateDate"])
            if ("updateDate" in json_data)
            else None
        )
        self.closeDate = (
            sq_datetime_to_date(json_data["closeDate"])
            if ("closeDate" in json_data)
            else None
        )

        # Issue effort/debt (should be the same value)
        if "effort" in json_data:
            assert json_data["effort"] == json_data["debt"]
        self.debt = (
            sq_duration_to_minutes(json_data["debt"]) if "debt" in json_data else "n/a"
        )

        # Handle issue severity
        if json_data["severity"] == "INFO":
            self.severity = Severity.INFO
        elif json_data["severity"] == "MINOR":
            self.severity = Severity.MINOR
        elif json_data["severity"] == "MAJOR":
            self.severity = Severity.MAJOR
        elif json_data["severity"] == "CRITICAL":
            self.severity = Severity.CRITICAL
        elif json_data["severity"] == "BLOCKER":
            self.severity = Severity.BLOCKER
        else:
            assert False, "Invalid issue severity"

        # Issue type
        if json_data["type"] == "CODE_SMELL":
            self.type = Type.CODE_SMELL
        elif json_data["type"] == "BUG":
            self.type = Type.BUG
        elif json_data["type"] == "VULNERABILITY":
            self.type = Type.VULNERABILITY
        else:
            assert False, "Invalid issue type"

        # Issue tag list
        # For the moment we just use strings, as there are many possible tags https://docs.sonarqube.org/latest/user-guide/built-in-rule-tags/
        # Also, tags are detailed in the sense of appearing not OWASP, but owasp-a4, which is good (extra detail) and not so good (enum would be too complicated)
        self.tags = param_list_to_strings(json_data["tags"])


class ProjectAnalysis:
    """
    Represents a SonarQube project analysis
    """

    def __init__(self, project, version, date):
        self.project = project
        self.version = version
        self.date = sq_datetime_to_date(date)


"""
    SonarQube API functions
"""


def api_metrics_search(sonarServerURL):
    """
    Retrieve the metric names from the given SonarQube instance (tested with SonaQube 7.9.1 Community Edition)
    params:
        sonarServerURL - URL of SonarQube server to use
    output:
        list of retrieved metric keys
    """
    logger.debug(
        "Contacting SonarQube server for metrics - "
        + sonarServerURL
        + METRIC_SEARCH_URL
    )
    r = requests.get(sonarServerURL + METRIC_SEARCH_URL, params={"ps": 500})
    data = r.json()

    # Process the JSON result
    result = []
    metricList = data["metrics"]
    for metric in metricList:
        # Metric key should be unique
        assert metric["key"] not in result
        result.append(metric["key"])
    logger.debug("Metrics retrieved - " + str(result))
    return result


def api_measures_search_history_xlsx(
    measures, xlsxOutput="./api_measures_search_history.xlsx"
):
    """
    Save the measures from @api_measures_search_history call to an XLSX file
    params:
        measures - The JSON return of an @api_measures_search_history call
        xlsxOutput - Output file
    """
    book = xlsxwriter.Workbook(xlsxOutput)
    outSheet = book.add_worksheet()
    cell_format = book.add_format()
    cell_format.set_num_format("0.000")

    # 1. Write date info to first column
    row = 1
    for date in measures["measures"][0]["history"]:
        outSheet.write(row, 0, date["date"][:10])
        row += 1

    # 2. Write each metric on its own column
    col = 1
    for metric in measures["measures"]:
        row = 0
        # Metric name goes in column header
        outSheet.write(row, col, metric["metric"])
        row = 1
        # Each row contains the metric value for the given date
        for metricValue in metric["history"]:
            if "value" in metricValue:
                outSheet.write(row, col, metricValue["value"])
            else:
                outSheet.write(row, col, "n/a")
            row += 1
        col += 1
    book.close()


def _sonar_qube_single_api_call(
    path, parameters, adminUser="admin", adminPassword="admin"
):
    """
    Generic call to SonarQube API
    params:
        path           - the GET path (e.g. '/api/projects/search')
        parameters     - dict of call parameters
        adminUser      - name of admin user account
        adminPassword  - password of admin user account
    """
    logger.debug("API: " + SONAR_SERVER_SINGLE_URL + path + "?" + str(parameters))
    r = requests.get(
        SONAR_SERVER_SINGLE_URL + path,
        auth=HTTPBasicAuth(adminUser, adminPassword),
        params=parameters,
    )
    return r.json()


def _sonar_qube_api_call(path, parameters, adminUser="admin", adminPassword="admin"):
    """
    Generic call to SonarQube API
    params:
        path           - the GET path (e.g. '/api/projects/search')
        parameters     - dict of call parameters
        adminUser      - name of admin user account
        adminPassword  - password of admin user account
    """
    logger.debug("API: " + SONAR_SERVER_HISTORY_URL + path + "?" + str(parameters))
    r = requests.get(
        SONAR_SERVER_HISTORY_URL + path,
        auth=HTTPBasicAuth(adminUser, adminPassword),
        params=parameters,
    )
    return r.json()


def api_projects_search():
    """
    Retrieve projects
    NB! Page size set to 500 (max value), so only the first 500 projects are returned
    output:
        List of retrieved project names
    """
    PROJECT_SEARCH_URL = "/api/projects/search"
    data = _sonar_qube_api_call(PROJECT_SEARCH_URL, {"ps": 500})

    result = []
    components = data["components"]
    for component in components:
        # Project key should be unique
        assert component["key"] not in result
        result.append(component["key"])
    return result


def api_project_analyses(project):
    """
    Return all analyses stored on server
    params:
        project - Project name (required)
    output:
        List of ProjectAnalysis instances
    """
    PROJECT_ANALYSES_URL = "/api/project_analyses/search"
    result_json = _sonar_qube_api_call(PROJECT_ANALYSES_URL, {"project": project})

    result = []
    for analysis in result_json["analyses"]:
        result.append(
            ProjectAnalysis(project, analysis["projectVersion"], analysis["date"])
        )
    return result


def api_measures_search_history(component, metrics):
    """
    Retrieve measure data history for SonarQube project(s) in the given instance (tested with SonarQube 8.2 Community Edition)
    Corresponds to /api/measures/search_history
    params:
        sonarServerURL - URL of SonarQube server to use
        component - the project/component key
        metrics - metrics for which to collect measures
    output:
        Dictionary-formatted JSON
    """
    MEASURES_SEARCH_HISTORY = "/api/measures/search_history"
    metricsString = param_list_to_strings(metrics)
    return _sonar_qube_api_call(
        MEASURES_SEARCH_HISTORY, {"component": component, "metrics": metricsString}
    )


def api_issues_search(
    languages=[], resolutions=[], types=["CODE_SMELL", "BUG", "VULNERABILITY"]
):
    """
    Returns all SonarQube issues
    NB! Implementation is complicated by the fact that SQ allows only 10k issues to be returned in 1 query.
    Solution is to first query project analysis dates and filter the returned issues by date
    (this makes sure all created issues are returned.)
    params:
        languages - List of languages to retrieve issues for
    output:
        List of issues. Each issue is a JSON-based dictionary as returned by the SonarQube API.
    """
    ISSUES_SEARCH = "/api/issues/search"
    PAGE_SIZE = 500
    result = []
    lang = param_list_to_strings(languages) if len(languages) > 0 else ""
    resol = param_list_to_strings(resolutions) if len(resolutions) > 0 else ""
    types = param_list_to_strings(types)
    # 1. Get project analyses
    project_analyses = {}
    for p in api_projects_search():
        project_analyses[p] = api_project_analyses(p)

    # 2. Get issues filtered by analysis date
    # NB! SonarQube cannot return more than 10k items for one filter!
    result = []
    for project in project_analyses.keys():
        analyses = project_analyses[project]
        # Sort analyses by ascending date to calculate issue lifetime
        analyses.sort(key=lambda x: x.date)
        for project_analysis in analyses:
            # Results have at least one page
            current_page = 0
            more_pages = True
            while more_pages == True:
                current_page += 1

                #
                # TODO
                # There are 2 *_api_call functions:
                # (a) hits the HISTORY server
                # (b) hits the SINGLE server
                #

                partial_result = _sonar_qube_api_call(
                    ISSUES_SEARCH,
                    {
                        "componentKeys": project_analysis.project,
                        "createdAt": str(project_analysis.date),
                        "ps": PAGE_SIZE,
                        "p": current_page,
                        "languages": lang,
                        "resolutions": resol,
                        "types": types,
                    },
                )

                # partial_result = _sonar_qube_single_api_call(ISSUES_SEARCH,
                #                                       {'componentKeys': project_analysis.project, 'createdAt': str(
                #                                           project_analysis.date), 'ps': PAGE_SIZE, 'p': current_page,
                #                                        'languages': lang, 'resolutions': resol, 'types': types})

                for issue in partial_result["issues"]:
                    new_issue = Issue(issue)
                    _set_issue_lifetime(new_issue, analyses)
                    result.append(new_issue)

                # Is there another page?
                issue_count = int(partial_result["total"])
                more_pages = current_page * PAGE_SIZE < issue_count
    return result


def api_measures_component(component, metricKeys):
    # This check is to avoid sending a string, which would then be split to chars
    if not isinstance(metricKeys, list):
        raise RuntimeError("Second parameter must be a Python list!")

    MEASURES_COMPONENT = "/api/measures/component"
    parameters = {
        "component": component,
        "metricKeys": param_list_to_strings(metricKeys),
    }

    # We do not use _sonar_qube_api_call as it does not support different SonarQube servers
    # logger.debug("API: " + SONAR_SERVER_SINGLE_URL + MEASURES_COMPONENT+"?"+str(parameters))
    r = requests.get(
        SONAR_SERVER_SINGLE_URL + MEASURES_COMPONENT,
        auth=HTTPBasicAuth("admin", "Parola123456789!"),
        params=parameters,
    )
    return r.json()


def api_cu_names(component):
    COMPONENT_TREE = "/api/components/tree"
    PAGE_SIZE = 500
    cu_list = []

    # Results have at least one page
    current_page = 0
    more_pages = True
    while more_pages:
        current_page += 1
        parameters = {
            "component": component,
            "ps": PAGE_SIZE,
            "p": current_page,
            "qualifiers": "FIL",
        }

        # We do not use _sonar_qube_api_call as it does not support different SonarQube servers
        # logger.debug("API: " + SONAR_SERVER_SINGLE_URL + MEASURES_COMPONENT+"?"+str(parameters))
        r = requests.get(
            SONAR_SERVER_SINGLE_URL + COMPONENT_TREE,
            auth=HTTPBasicAuth("admin", "Parola123456789!"),
            params=parameters,
        )
        cu_dict = r.json()

        for cu in cu_dict["components"]:
            cu_list.append(cu["key"])

        # Is there another page?
        cu_count = int(cu_dict["paging"]["total"])
        more_pages = current_page * PAGE_SIZE < cu_count

    return cu_list
