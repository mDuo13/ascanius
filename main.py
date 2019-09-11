#!/usr/bin/env python3

import argparse
import ruamel.yaml
import sys
import jinja2
import re
import os

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
TOC_FILE = "xrp-api-reference.md"
DATA_TYPES_FILE = "xrp-api-data-types.md"

yaml = ruamel.yaml.YAML(typ="safe")

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
        self.write_file(self.render_toc(), TOC_FILE)

        for path, path_def in self.swag["paths"].items():
            #TODO: inherit path-generic fields
            for method in HTTP_METHODS:
                if method in path_def.keys():
                    endpoint = path_def[method]
                    to_file = method_file(path, method, endpoint)
                    self.write_file(self.render_endpoint(path, method, endpoint), to_file)

        self.write_file(self.render_data_types(), DATA_TYPES_FILE)

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
    return DATA_TYPES_FILE.replace(".md",".html")+"#"+slugify(title.lower())

def method_link(path, method, endpoint):
    return slugify(endpoint["operationId"]+".html")

def method_file(path, method, endpoint):
    return slugify(endpoint["operationId"]+".md")

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
