"""
Generates JSON format question-answer pairs and instructions for a Python file
Requirements:
[req01] The `DatasetGenerator` class shall:
        a. Accept Python file path, file details, base name, list of questions,
        and model configuration as input during instantiation.
        b. Initialize and store Python file path, file details, base name,
        question list, llm, and use_llm flag as class attributes.
        d. Provide `get_response_from_llm` method to retrieve llm response.
        e. Provide `process_question` method to process each question, generate
        corresponding responses, and add to the instruct_list.
        f. Provide `process_question_type` method to process questions
        related to the file, functions, classes, and methods.
        g. Provide `generate` method to generate responses for all questions
        and return the instruct_list.
        h. Internally manage question mapping to file details.
[req02] The `get_python_datasets` function shall:
        a. Accept a Python file path, file details, base name, questions list,
        and model config as input.
        b. Instantiate `DatasetGenerator` class using the provided input.
        c. Generate instruct_list using `DatasetGenerator` `generate` method.
        d. Return the generated `instruct_list`.
[req03] The `clean_and_get_unique_elements` function shall:
        a. Clean an input string (str) and return a string of unique elements.
"""
import logging
import re
import math
import json
from typing import Dict, List, Tuple


def clean_and_get_unique_elements(input_str: str) -> str:
    """
    Clean an input string (str) and return a string of unique elements.
    Args:
        input_str (str): The input string to be cleaned.
    Returns:
        str: The cleaned string.
    """

    def element_generator(input_str):
        start, brace_level = 0, 0
        for i, char in enumerate(input_str):
            if char in "{}":
                brace_level += 1 if char == "{" else -1
            elif char == "," and brace_level == 0:
                yield input_str[start:i]
                start = i + 1
        yield input_str[start:]

    input_str = input_str.strip("[]'\"").strip()
    cleaned_elements = [
        element.strip("'\" ").strip()
        for element in element_generator(input_str)
        if element.strip()
    ]
    returned_elements = ", ".join(cleaned_elements)
    return returned_elements


class DatasetGenerator:
    """
    Generate JSON formatted dictionary outputs for a Python file.
    Attributes:
        file_path (str): The path to the Python file.
        file_details (Dict[str, Any]): Details of the Python file.
        base_name (str): The base name of the Python file.
        questions (List[Dict[str, str]]): Questions for generating responses.
        instruct_list (List[Dict[str, str]]): Storage for generated instructions.
        question_mapping (Dict[str, str]): Mapping of question types to keys in file details.
        use_llm (bool): Flag indicating if a language model should be used.
        llm (object): The language model for generating responses.
        prompt (str): The prompt format for querying the language model.
    Methods:
        get_response_from_llm(query: str, context: str) -> str:
            Get language model response to query for given context.
        process_question(question_type: str, question_id: str, query: str, context: str, info: Dict) -> None:
            Process question and add the generated response to the instruct_list.
        get_info_string(info, item_type) -> str:
            Get string from info dictionary.
        process_question_type(question_type: str, question_id: str, question_text: str) -> None:
            Process questions related to a file, function, class, or method.
        generate() -> Tuple[List[Dict], List[Dict]]:
            Generate responses for all the questions and returns the instruct_list.
    """

    def __init__(
        self,
        file_path: str,
        file_details: Dict,
        base_name: str,
        questions: List[Dict],
        model_config: Dict,
        detailed: bool,
    ) -> None:
        """
        Initialize the DatasetGenerator class.
        Args:
            file_path (str): The path to the Python file.
            file_details (Dict[str, Any]): Details of the Python file.
            base_name (str): The base name of the Python file.
            questions (List[Dict[str, str]]): Questions for generating responses.
            model_config (Dict): Configuration for the language model.
        Returns:
            None
        """
        self.file_path = file_path
        self.file_details = file_details
        self.base_name = base_name
        self.questions = questions
        self.model_config = model_config
        if model_config is not None:
            self.llm = model_config["model"]
            self.use_llm = True
            self.detailed = detailed
        else:
            self.llm = None
            self.use_llm = False
            self.detailed = False
        self.instruct_list = []
        self.question_mapping = {
            "file": "file",
            "function": "functions",
            "class": "classes",
            "method": "classes",
        }

    def get_response_from_llm(self, query: str, context: str) -> str:
        """
        Get language model response to query for given context.
        Args:
            query (str): The query to be used for generating the response.
            context (str): The context to be used for generating the response.
        Returns:
            str: The generated response.
        """
        excluded_instructions = ["Call code graph", "Docstring"]
        code_qa_list = [
            {item["instruction"].split(
                "are in Python file",
                " in Python file:",
                "of the Python file")[0]: item["output"]}
            for item in self.instruct_list
            if not any(
                item["instruction"].startswith(prefix)
                for prefix in excluded_instructions
            )
        ]
        code_qa_dict = {
            "Code Elements": {
                f"{key.split()[-1]} {key.split()[0]}" if "`" in key else key: value
                for item in code_qa_list
                for key, value in item.items()
            }
        }

        context_strategies = [
            lambda: "{}".format(str(context)),
            lambda: "```python\n{}\n```".format(
                str(self.file_details["file_info"]["file_code_simplified"])
            ),
            lambda: "```python\n{}\n```".format(
                self.get_info_string(self.file_details["file_info"], "file_summary")
            ),
            lambda: "",
        ]

        max_context_length = self.model_config["inference_model"]["model_params"][
            "context_length"
        ]
        prompt_template = self.model_config["prompt_template"].format(
            system_prompt=self.model_config["system_prompt"],
            instruction_prompt=self.model_config["instruction_prompt"],
        )

        for strategy in context_strategies:
            context = strategy()
            full_context = f"{context}\n{code_qa_dict}"
            prompt = prompt_template.format(context=full_context, query=query)
            context_size = len(self.llm.tokenize(prompt))
            logging.info("***Context Size: " + str(context_size))
            if context_size <= 0.70 * max_context_length:
                break
        else:
            err_msg = f"Model response failed, increase py2dataset_model_config.yaml context_length > {math.ceil(context_size/0.70)}"
            logging.error(err_msg)
            return ""

        response = ""
        try:
            response = re.sub(r"\n\s*\n", "\n\n", self.llm(prompt))
            response += "\n" + json.dumps(code_qa_dict, indent=4)
            logging.info(f"***Overall Response: {response}")
        except Exception as error:
            logging.error(f"Failed to generate model response: {error}")

        if (
            self.detailed
        ):  # add llm_response for each code object to self.instruct_list "output"
            for item in code_qa_list:
                try:
                    instruct_key = list(item.keys())[0]
                    instruct_value = list(item.values())[0]
                    query = f"Describe the purpose and significance of these {instruct_key}: [{instruct_value}] within the code."
                    prompt = (
                        self.model_config["prompt_template"]
                        .format(
                            system_prompt=self.model_config["system_prompt"],
                            instruction_prompt=self.model_config["instruction_prompt"],
                        )
                        .format(context=full_context, query=query)
                    )

                    item_response = re.sub(r"\n\s*\n", "\n\n", self.llm(prompt))
                    logging.info(f"\n***Itemized Response: {query}\n{item_response}")
                    for item in self.instruct_list:
                        if item["instruction"].startswith(instruct_key):
                            output = f"\n\nPurpose and Significance:\n{item_response}"
                            item["output"] += output
                            break

                except Exception as error:
                    logging.error(f"Failed to generate model response: {error}")

        return response

    def process_question(
        self, question_type: str, question_id: str, query: str, context: str, info: Dict
    ) -> None:
        """
        Process question and add the generated response to the instruct_list.
        Args:
            question_type (str): The type of question to be processed.
            question_id (str): The ID of the question to be processed.
            query (str): The query to be processed.
            context (str): The context to be used for generating the response.
            info (Dict): The information of the Python file.
        Returns:
            None
        """
        if question_id.endswith(("code_graph", "docstring")):
            response = info.get(question_id, {})
        elif self.use_llm and question_id.endswith("purpose"):
            response = self.get_response_from_llm(query, context)
        else:
            response = clean_and_get_unique_elements(str(info.get(question_id, "")))
        response = str(response).strip()

        if response and response != "None":
            context = f"```python\n{context}\n```"
            self.instruct_list.append(
                {"instruction": query, "input": context, "output": response}
            )

    @staticmethod
    def get_info_string(info: Dict, item_type: str) -> str:
        """
        Get string from info dictionary.
        Args:
            info (Dict): The information of the Python file.
            item_type (str): The type of item to get the string from.
        Returns:
            str: The string from the info.
        """
        return ", ".join(
            [item.strip() for item in str(info.get(item_type, "")).split(",") if item]
        )

    def process_question_type(
        self, question_type: str, question_id: str, question_text: str
    ) -> None:
        """
        Process questions related to a file, function, class, or method.
        Args:
            question_type (str): The type of question to be processed.
            question_id (str): The ID of the question to be processed.
            question_text (str): The text of the question to be processed.
        Returns:
            None
        """
        if question_type == "file":
            query = question_text.format(filename=self.base_name)
            info = self.file_details["file_info"]
            context = self.file_details["file_info"]["file_code"]
            self.process_question(question_type, question_id, query, context, info)
        elif question_type == "method":
            for class_name, class_info in self.file_details["classes"].items():
                for key, method_info in class_info.items():
                    if key.startswith("class_method_"):
                        method_name = f"{class_name}.{key[len('class_method_'):]}"
                        context = method_info["method_code"]
                        mapping = {"class_name": class_name, "method_name": method_name}
                        query = question_text.format(filename=self.base_name, **mapping)
                        self.process_question(
                            question_type, question_id, query, context, method_info
                        )
        else:  # question_type is 'function' or 'class'
            for name, info in self.file_details[
                self.question_mapping[question_type]
            ].items():
                context = info[f"{question_type}_code"]
                mapping = {f"{question_type}_name": name}
                if question_id == f"{question_type}_purpose" and self.use_llm:
                    variables = self.get_info_string(info, f"{question_type}_variables")
                    inputs = self.get_info_string(info, f"{question_type}_inputs")
                    combined = ", ".join([s for s in [variables, inputs] if s])
                    mapping[
                        f"{question_type}_variables"
                    ] = clean_and_get_unique_elements(combined)

                    if question_type == "class":
                        methods_string = self.get_info_string(
                            info, f"{question_type}_methods"
                        )
                        mapping[f"{question_type}_methods"] = methods_string

                query = question_text.format(filename=self.base_name, **mapping)
                self.process_question(question_type, question_id, query, context, info)

    def generate_instructions(self, context: str, iteratino: int = 0) -> List[Dict]:
        max_context_length = self.model_config["inference_model"]["model_params"][
            "context_length"
        ]

        prompt_template = self.model_config["prompt_template"].format(
            system_prompt=self.model_config["system_prompt"],
            instruction_prompt=self.model_config["instruction_gen_prompt_2"],
        )

        prompt = prompt_template.format(context=context)
        context_size = len(self.llm.tokenize(prompt))
        logging.info("***Context Size: " + str(context_size))

        if context_size > 0.70 * max_context_length:
            err_msg = f"Model response failed, increase py2dataset_model_config.yaml context_length > {math.ceil(context_size/0.70)}"
            logging.error(err_msg)
            return ""

        response = ""
        try:
            response = re.sub(r"\n\s*\n", "\n\n", self.llm(prompt))
            logging.info(f"***Overall Response: {response}")
        except Exception as error:
            logging.error(f"Failed to generate model response: {error}")

        # get all indeces of all occurences of 'In the context of Home Assistant' in response
        indices = [m.start() for m in re.finditer("In the context of Home Assistant", response)]

        if indices == []:
            logging.error("Failed to generate instructions: No instructions found")
            logging.error("Response: " + response)
            logging.error("Prompt: " + prompt)
            if iteratino > 1:
                # exit(1)
                return ""
            return self.generate_instructions(context, iteratino + 1)

        response = response[indices[0]:]
        instructions = []
        for i, _ in enumerate(indices):
            if i == len(indices) - 1:
                instructions.append(response[indices[i]-indices[0]:])
            else:
                instructions.append(response[indices[i]-indices[0]:indices[i+1]-indices[0]])

        return instructions

    def generate_instruction_response(self, instruction: str, context: str) -> str:
        context = self.file_details["file_info"]["file_code"]
        max_context_length = self.model_config["inference_model"]["model_params"][
            "context_length"
        ]
        prompt_template = self.model_config["prompt_template"].format(
            system_prompt=self.model_config["system_prompt"],
            instruction_prompt=self.model_config["instruction_prompt"],
        )

        prompt = prompt_template.format(context=context, query=instruction)
        context_size = len(self.llm.tokenize(prompt))
        logging.info("***Context Size: " + str(context_size))

        if context_size > 0.70 * max_context_length:
            err_msg = f"Model response failed, increase py2dataset_model_config.yaml context_length > {math.ceil(context_size/0.70)}"
            logging.error(err_msg)

        response = ""
        try:
            response = re.sub(r"\n\s*\n", "\n\n", self.llm(prompt))
            logging.info(f"***Overall Response: {response}")
        except Exception as error:
            logging.error(f"Failed to generate model response: {error}")

        return response

    def get_file_contents(self) -> List[str]:
        objects = []
        objects.append(self.file_details["file_info"]["file_code"])
        for class_name, class_info in self.file_details["classes"].items():
            for key, method_info in class_info.items():
                if key.startswith("class_method_"):
                    method_name = f"# {class_name}.{key[len('class_method_'):]}"
                    context = method_name + "\n" + method_info["method_code"]
                    objects.append(context)
        return objects

    def process_generated_instructions(self) -> None:
        objects = self.get_file_contents()
        for context in objects:
            logging.info("Processing context: " + context.replace("\n", " ")[:80] + " ...")
            instructions = self.generate_instructions(context)

            for instruction in instructions:
                response = self.generate_instruction_response(instruction, context)
                response = str(response).strip()
                self.instruct_list.append(
                    {"instruction": instruction, "input": "", "output": response}
                )

    def generate(self) -> Tuple[List[Dict], List[Dict]]:
        """
        Generate responses for all the questions and returns the instruct_list.
        Args:
            None
        Returns:
            Tuple[List[Dict], List[Dict]]: The generated question-answer pairs and instructions.
        """
        # for question in self.questions:
        #     self.process_question_type(
        #         question["type"], question["id"], question["text"]
        #     )

        self.process_generated_instructions()

        return self.instruct_list


def get_python_datasets(
    file_path: str,
    file_details: Dict,
    base_name: str,
    questions: List[Dict],
    model_config: Dict,
    detailed: bool,
) -> Tuple[List[Dict], List[Dict]]:
    """
    Extract information from a Python file and return it in JSON format.
    Args:
        file_path (str): The path to the Python file.
        file_details (Dict): The details of the file.
        base_name (str): The base Python code filename.
        questions (List[Dict]): The list of questions.
        llm (object): The language model to be used for generating responses.
        prompt (str): The prompt to be used for generating responses.
        detailed (bool): Flag indicating if detailed information should be extracted.
    Returns:
        Tuple[List[Dict], List[Dict]]: Extracted information in JSON format.
    """
    return DatasetGenerator(
        file_path, file_details, base_name, questions, model_config, detailed
    ).generate()
