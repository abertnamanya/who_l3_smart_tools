import re
from datetime import datetime, timezone
from typing import Any
import stringcase
import pandas as pd

from who_l3_smart_tools.utils.cql_helpers import (
    determine_scoring_from_cql,
    determine_scoring_suggestion,
)


library_fsh_template = """
Instance: {library_name}
InstanceOf: Library
Title: "{title} Logic"
Description: "{description}"
Usage: #definition
* meta.profile[+] = "http://hl7.org/fhir/uv/crmi/StructureDefinition/crmi-shareablelibrary"
* meta.profile[+] = "http://hl7.org/fhir/uv/crmi/StructureDefinition/crmi-publishablelibrary"
* meta.profile[+] = "http://hl7.org/fhir/uv/cql/StructureDefinition/cql-library"
* meta.profile[+] = "http://hl7.org/fhir/uv/cql/StructureDefinition/cql-module"
* url = "http://smart.who.int/{dak_name}/Library/{library_name}"
* extension[+]
  * url = "http://hl7.org/fhir/StructureDefinition/cqf-knowledgeCapability"
  * valueCode = #computable
* name = "{library_name}"
* status = #draft
* experimental = true
* publisher = "World Health Organization (WHO)"
* type = $library-type#logic-library
* content.id = "ig-loader-{library_name}.cql"
"""

measure_fsh_template = """
Instance: {measure_name}
InstanceOf: {measure_instance}
Title: "{title}"
* meta.profile[+] = "http://hl7.org/fhir/uv/crmi/StructureDefinition/crmi-shareablemeasure"
* meta.profile[+] = "http://hl7.org/fhir/uv/crmi/StructureDefinition/crmi-publishablemeasure"
* extension[http://hl7.org/fhir/us/cqfmeasures/StructureDefinition/cqfm-populationBasis].valueCode = #boolean
* description = "{description}"
* url = "http://smart.who.int/{dak_name}/Measure/{measure_name}"
* status = #draft
* experimental = true
* date = "{date}"
* name = "{measure_name}"
* title = "{title}"
* publisher = "World Health Organization (WHO)"
* library = "http://smart.who.int/{dak_name}/Library/{measure_name}Logic"
"""

scoring_value_set: str = {"proportion", "continuous-variable"}

measure_scoring_fsh_template = """
* scoring = $measure-scoring#{scoring} "{scoring_title}"
"""

measure_initial_population_fsh_template = """
  * population[initialPopulation]
    * id = "{dak_id}.IP"
    * description = "Initial Population"
    * code = $measure-population#initial-population "Initial Population"
    * criteria.language = #text/cql-identifier
    * criteria.expression = "Initial Population"
"""

measure_measure_population_fsh_template = """
  * population[measurePopulation]
    * extension[http://hl7.org/fhir/us/cqfmeasures/StructureDefinition/cqfm-populationBasis].valueCode = #boolean
    * id = "{dak_id}.MP"
    * description = "Measure Population"
    * code = $measure-population#measure-population "Measure Population"
    * criteria.language = #text/cql-identifier
    * criteria.expression = "Measure Population"
"""

measure_measure_observation_fsh_template = """
  * population[measureObservation]
    * extension[http://hl7.org/fhir/us/cqfmeasures/StructureDefinition/cqfm-criteriaReference].valueString = "measure-population"
    * extension[http://hl7.org/fhir/us/cqfmeasures/StructureDefinition/cqfm-aggregateMethod].valueCode = #count
    * id = "{dak_id}.MO"
    * description = "Measure Observation"
    * code = $measure-population#measure-observation "Measure Observation"
    * criteria.language = #text/cql-identifier
    * criteria.expression = "Measure Observation"
"""

measure_denominator_fsh_template = """
  * population[denominator]
    * id = "{dak_id}.DEN"
    * description = "{description}"
    * code = $measure-population#denominator "Denominator"
    * criteria.language = #text/cql-identifier
    * criteria.expression = "Denominator"
"""

measure_numerator_fsh_template = """
  * population[numerator]
    * id = "{dak_id}.NUM"
    * description = "{description}"
    * code = $measure-population#numerator "Numerator"
    * criteria.language = #text/cql-identifier
    * criteria.expression = "Numerator"
"""

measure_stratifier_fsh_template = """
  * stratifier[+]
    * id = "{dak_id}.S.{strat_code}"
    * criteria.language = #text/cql-identifier
    * criteria.expression = "{index}"
"""


# Get indicator DAK ID from CQL file with first instance of DAK ID pattern HIV.IND.X
# TODO: generalize this pattern to match any DAK
DAK_INDICATOR_ID_PATTERN = re.compile(r"(HIV\.IND\.\d+)")


class EmptyItem:
    def __getitem__(self, item) -> Any:
        return None

    def keys(self):
        return []


__empty__ = EmptyItem()


class CqlResourceGenerator:
    """
    This class assists in the translation of L2 DAK indicator artifacts into
    CQL and related resources for loading into the IG.

    Attributes:
        cql_content (str): The content of the CQL file.
        indicator_dictionary (dict): The row of the indicator artifact.
    """

    def __init__(self, cql_content: str, indicator_dictionary: dict[str, Any]):
        self.cql_content = cql_content
        self.parsed_cql = __empty__
        self.parse_cql()
        self.indicator_dictionary = indicator_dictionary

    def parseRow(self, row):
        """
        This method converts the indicator row into a dictionary.
        """
        return row.to_dict()

    def parse_cql(self):
        """
        Parse the CQL file to extract relevant information.
        """
        if self.parsed_cql is not __empty__:
            return self.parsed_cql

        parsed_data = {
            "templateOnly": None,
            "stratifiers": {},
            "initialPopulation": False,
            "measurePopulation": False,
            "measureObservation": False,
            "numerator": False,
            "denominator": False,
            "library_name": None,
        }

        # Don't parse if CQL contents are generated only,
        # without any content for the indicator definition itself

        # Find where the indicator header location is
        indicator_header_match = re.search(
            r"// Indicator Definition(.*)", self.cql_content, re.DOTALL
        )

        if indicator_header_match:
            content_after_match = indicator_header_match.group(1)

            # Check if the content after the match is not just whitespace
            if content_after_match.strip():
                parsed_data["templateOnly"] = False
            else:
                parsed_data["templateOnly"] = True

        indicator_match = DAK_INDICATOR_ID_PATTERN.search(self.cql_content)

        if indicator_match:
            parsed_data["library_name"] = indicator_match.group(1)
            parsed_data["is_indicator"] = True
        else:
            parsed_data["is_indicator"] = False
            non_indicator_name = non_indicator_name = re.search(
                r"^library\s(\w+)\s.*$", self.cql_content, re.MULTILINE
            )
            parsed_data["library_name"] = (
                non_indicator_name.group(1) if non_indicator_name else None
            )

        if not parsed_data["library_name"]:
            raise ValueError("Could not find library name in CQL file.")

        # chomp "Logic" off the ned of the library name
        if parsed_data["library_name"].endswith("Logic"):
            parsed_data["library_name"] = parsed_data["library_name"][:-5]

        # Extract denominator, if exists:
        denominator_match = re.search(
            r"define \"denominator\"\:", self.cql_content, re.IGNORECASE
        )
        if denominator_match:
            parsed_data["denominator"] = True

        # Extract numerator, if exists:
        numerator_match = re.search(
            r"define \"numerator\"\:", self.cql_content, re.IGNORECASE
        )
        if numerator_match:
            parsed_data["numerator"] = True

        # Extract stratifiers
        stratifier_matches = re.findall(r'define "(.+ Stratifier)":', self.cql_content)
        for stratifier in stratifier_matches:
            parsed_data["stratifiers"][stratifier] = True

        # Extract initial population
        initial_population_match = re.search(
            r"define \"Initial Population\"\:", self.cql_content, re.IGNORECASE
        )
        if initial_population_match:
            parsed_data["initialPopulation"] = True

        # Extract measure population
        measure_population_match = re.search(
            r"define \"Measure Population\"\:", self.cql_content, re.IGNORECASE
        )
        if measure_population_match:
            parsed_data["measurePopulation"] = True

        # Extract measure observation
        measure_observation_match = re.search(
            r"define function \"Measure Observation\"",
            self.cql_content,
            re.IGNORECASE,
        )
        if measure_observation_match:
            parsed_data["measureObservation"] = True

        # Extract population exclusions
        population_exclusion_matches = re.findall(
            r'define "(.+ Population Exclusion)":', self.cql_content
        )
        for population_exclusion in population_exclusion_matches:
            parsed_data["population exclusions"][population_exclusion] = True

        self.parsed_cql = parsed_data
        return self.parsed_cql

    def generate_library_fsh(self):
        """
        Generate the Library FSH file content.
        """

        raw_library_name: str = self.parsed_cql["library_name"]
        dak_name = raw_library_name.split(".")[0]
        library_name = f"{raw_library_name.replace('.', '')}Logic"

        # Treat as indicator
        if raw_library_name in self.indicator_dictionary.keys():
            header_variables = self.parseRow(
                self.indicator_dictionary[raw_library_name]
            )
            title = raw_library_name
            description = header_variables["Indicator definition"]
        else:
            title = raw_library_name
            description = f"Description not yet available for {library_name}."

        library_fsh = library_fsh_template.format(
            library_name=library_name,
            title=title,
            description=description,
            dak_name=dak_name,
        )

        return library_fsh

    def generate_measure_fsh(self):
        if not self.parsed_cql["is_indicator"] or self.parsed_cql["templateOnly"]:
            return None

        dak_name = self.parsed_cql["library_name"].split(".")[0]

        header_variables = self.parseRow(
            self.indicator_dictionary[self.parsed_cql["library_name"]]
        )
        indicator_row = self.indicator_dictionary[self.parsed_cql["library_name"]]

        dak_id = header_variables["DAK ID"]
        measure_name = header_variables["DAK ID"].replace(".", "")
        title = f"{header_variables['DAK ID']} {header_variables['Short name']}"
        description = header_variables["Indicator definition"]

        # Determine scoring based on parsed cql entries
        scoring, scoring_title, scoring_instance = determine_scoring_from_cql(
            self.parsed_cql
        )

        if not scoring:
            print("Could not determine scoring for measure - failed to generate FSH.")
            return None

        # Generate the Measure FSH file content.
        measure_fsh = measure_fsh_template.format(
            measure_name=measure_name,
            title=title,
            description=description,
            measure_instance=scoring_instance,
            dak_name=dak_name,
            date=datetime.now(timezone.utc).date().isoformat(),
        )

        measure_fsh += measure_scoring_fsh_template.format(
            scoring=scoring, scoring_title=scoring_title
        )

        # Add Populations and Stratifiers to the measure FSH string if group is not empty
        if (
            self.parsed_cql["stratifiers"]
            or self.parsed_cql["initialPopulation"]
            or self.parsed_cql["measurePopulation"]
            or self.parsed_cql["denominator"]
            or self.parsed_cql["numerator"]
        ):
            measure_fsh += "\n* group[+]\n"

            if self.parsed_cql["initialPopulation"]:
                measure_fsh += measure_initial_population_fsh_template.format(
                    population_camel_case="initialPopulation",
                    dak_id=dak_id,
                    pop_code="IP",
                    pop_string="initial-population",
                    population="Initial Population",
                )

            if self.parsed_cql["measurePopulation"]:
                measure_fsh += measure_measure_population_fsh_template.format(
                    population_camel_case="measurePopulation",
                    dak_id=dak_id,
                    pop_code="MP",
                    pop_string="measure-population",
                    population="Measure Population",
                )

            if self.parsed_cql["measureObservation"]:
                measure_fsh += measure_measure_observation_fsh_template.format(
                    population_camel_case="measureObservation",
                    dak_id=dak_id,
                    pop_code="MO",
                    pop_string="measure-observation",
                    population="Measure Observation",
                )

            if self.parsed_cql["denominator"]:
                measure_fsh += measure_denominator_fsh_template.format(
                    dak_id=dak_id,
                    description=indicator_row["Denominator definition"],
                )

            if self.parsed_cql["numerator"]:
                measure_fsh += measure_numerator_fsh_template.format(
                    dak_id=dak_id,
                    description=indicator_row["Numerator definition"],
                )

            for index, stratifier in self.parsed_cql["stratifiers"].items():
                # Remove last word from stratifier title, and use first letter of each remaining word to create code
                words = index.split()
                strat_code = "".join([word[0] for word in words[:-1]]).upper()
                measure_fsh += measure_stratifier_fsh_template.format(
                    dak_id=dak_id, strat_code=strat_code, index=index
                )

        # remove any empty lines from measure
        measure_fsh = "\n".join(
            [line for line in measure_fsh.split("\n") if line.strip()]
        )
        return measure_fsh

    def get_library_name(self):
        return self.parsed_cql["library_name"]

    def is_indicator(self):
        return self.parsed_cql["is_indicator"]
