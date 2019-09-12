#!/usr/bin/env python3

import argparse
import ruamel.yaml
import sys
import jinja2
import re
import os

from copy import deepcopy

TOC_TEMPLATE = "toc.md.jinja2"
ENDPOINT_TEMPLATE = "endpoint.md.jinja2"
DATA_TYPES_TEMPLATE = "datatypes.md.jinja2"

HTTP_METHODS = [
    "get",
    "put",
    "post",
    "delete",
    "options",
    "head",
    "patch",
    "trace",
]

OUT_DIR = "./out"
API_SLUG = "xrp-api"
DATA_TYPES_SUFFIX = "-data-types"
METHOD_TOC_SUFFIX = "-methods"
YAML_MD_PATH = "references/xrp-api/"
YAML_OUT_FILE = API_SLUG+"-test.yml"

yaml = ruamel.yaml.YAML(typ="safe")
yaml.indent(offset=4, sequence=4, mapping=8)

def parse_cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("api_def")
    return parser.parse_args()

class ApiDef:
    def __init__(self, fname):
        with open(fname, "r", encoding="utf-8") as f:
            self.swag = yaml.load(f)
        self.env = jinja2.Environment(loader=jinja2.FileSystemLoader("templates"))
        self.out_dir = OUT_DIR
        try:
            self.api_title = self.swag["info"]["title"]
        except IndexError:
            self.api_title = fname.replace(".yml","")+" API (working title)"

    def deref(self, ref, add_title=False):
        assert len(ref) > 1 and ref[0] == "#" and ref[1] == "/"
        parts = ref[2:].split("/")
        assert len(parts) > 0

        def dig(parts, context):
            key = parts[0].replace("~1", "/").replace("~0", "~") # unescaped
            try:
                key = int(key)
            except:
                pass
            if key not in context.keys():
                raise IndexError(key)

            if len(parts) == 1:
                if add_title:
                    context[key]["title"] = parts[0]
                return context[key]
            else:
                return dig(parts[1:], context[key])

        return dig(parts, self.swag)

    def render(self):
        self.write_file(self.render_toc(), API_SLUG+METHOD_TOC_SUFFIX+".md")

        for path, path_def in self.swag["paths"].items():
            #TODO: inherit path-generic fields
            for method in HTTP_METHODS:
                if method in path_def.keys():
                    endpoint = path_def[method]
                    to_file = method_file(path, method, endpoint)
                    self.write_file(self.render_endpoint(path, method, endpoint), to_file)

        self.write_file(self.render_data_types(), API_SLUG+DATA_TYPES_SUFFIX+".md")

    def render_toc(self):
        t = self.env.get_template(TOC_TEMPLATE)
        context = self.new_context()
        return t.render(self.swag, **context)

    def render_data_types(self):
        t = self.env.get_template(DATA_TYPES_TEMPLATE)
        context = self.new_context()
        schemas = self.swag["components"]["schemas"]

        # Dereference properties first
        for cname, c in schemas.items():
            if "properties" in c.keys():
                for pname, p in c["properties"].items():
                    if "$ref" in p.keys():
                        schemas[cname]["properties"][pname] = self.deref(p["$ref"])

        # Dereference aliased data types
        for cname, c in schemas.items():
            if "$ref" in c.keys():
                schemas[cname] = self.deref(c["$ref"])

        return t.render(**context, schemas=schemas)

    def render_endpoint(self, path, method, endpoint):
        t = self.env.get_template(ENDPOINT_TEMPLATE)
        context = self.new_context()
        context["method"] = method
        context["path"] = path
        context["path_params"] = [p for p in endpoint.get("parameters",[]) if p["in"]=="path"]
        for p in context["path_params"]:
            if "schema" in p.keys() and "$ref" in p["schema"].keys():
                p["schema"] = self.deref(p["schema"]["$ref"], add_title=True)
                # add_title is a hack since the XRP-API ref doesn't use titles
        context["query_params"] = [p for p in endpoint.get("parameters",[]) if p["in"]=="query"]
        for p in context["path_params"]:
            if "schema" in p.keys() and "$ref" in p["schema"].keys():
                p["schema"] = self.deref(p["schema"]["$ref"], add_title=True)
        #TODO: header & cookie params??
        return t.render(endpoint, **context)

    def create_pagelist(self):

        README_URL = "https://raw.githubusercontent.com/intelliot/xrp-api/master/README.md" #TODO: move

        GENERIC_PROPERTIES = {
            "funnel": "Docs",
            "doc_type": "References",
            "supercategory": "XRP-API",
            "targets": ["local"]
        }

        pages = []
        # add README
        readme = deepcopy(GENERIC_PROPERTIES)
        readme.update({
            "md": README_URL,
            "html": API_SLUG+".html",
        })
        pages.append(readme)

        # add data types page
        data_types_page = deepcopy(GENERIC_PROPERTIES)
        data_types_page.update({
           "md": YAML_MD_PATH+API_SLUG+DATA_TYPES_SUFFIX+".md",
           "html": API_SLUG+DATA_TYPES_SUFFIX+".html",
           "blurb": "Definitions for all data types in "+self.api_title, #TODO: template so it's translatable
           "category": self.api_title+" Conventions", #TODO: template
       })
        pages.append(data_types_page)

        # add toc
        toc_page = deepcopy(GENERIC_PROPERTIES)
        toc_page.update({
            "md": YAML_MD_PATH+API_SLUG+METHOD_TOC_SUFFIX+".md",
            "html": API_SLUG+METHOD_TOC_SUFFIX+".html",
            "blurb": "List of methods/endpoints available in "+self.api_title, #TODO: template
            "category": self.api_title+" Methods", #TODO: template
        })
        pages.append(toc_page)

        for path, path_def in self.swag["paths"].items():
            for method in HTTP_METHODS:
                if method in path_def.keys():
                    endpoint = path_def[method]

                    method_page = deepcopy(GENERIC_PROPERTIES)
                    method_page.update({
                        "md": YAML_MD_PATH+method_file(path, method, endpoint),
                        "html": method_link(path, method, endpoint),
                        "blurb": endpoint.get("description", endpoint["operationId"]+" method"),
                        "category": self.api_title+" Methods",
                    })
                    pages.append(method_page)

        yaml2 = ruamel.yaml.YAML()
        yaml2.indent(offset=4, sequence=8)
        out_path = os.path.join(OUT_DIR, YAML_OUT_FILE)
        with open(out_path, "w", encoding="utf-8") as f:
            yaml2.dump({"pages":pages}, f)

    def new_context(self):
        return {
            "type_link": type_link,
            "method_link": method_link,
            "HTTP_METHODS": HTTP_METHODS,
        }

    def write_file(self, page_text, filepath):
        out_folder = os.path.join(self.out_dir, os.path.dirname(filepath))
        if not os.path.isdir(out_folder):
            os.makedirs(out_folder)
        fileout = os.path.join(out_folder, filepath)
        with open(fileout, "w", encoding="utf-8") as f:
            f.write(page_text)


def type_link(title):
    return API_SLUG+DATA_TYPES_SUFFIX+".html#"+slugify(title.lower())

def method_link(path, method, endpoint):
    return API_SLUG+"-"+slugify(endpoint["operationId"]+".html")

def method_file(path, method, endpoint):
    return API_SLUG+"-"+slugify(endpoint["operationId"]+".md")

unacceptable_chars = re.compile(r"[^A-Za-z0-9._ ]+")
whitespace_regex = re.compile(r"\s+")
def slugify(s):
    s = re.sub(unacceptable_chars, "", s)
    s = re.sub(whitespace_regex, "_", s)
    if not s:
        s = "_"
    return s


if __name__ == "__main__":
    args = parse_cli()
    ref = ApiDef(args.api_def)
    ref.render()
    ref.create_pagelist()
