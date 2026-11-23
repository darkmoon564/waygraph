"""Command-line interface for the pilot."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path
from dotenv import load_dotenv
from .graph import Graph
from .evaluation import run, run_repeats
from .agent_runner import run_agent_evaluation
from .mutations import run_matrix
from .questions import freeze_question_set, generate
from .shortcuts import learn,reuse

def main() -> None:
    # Keep project secrets local; inherited shell variables remain authoritative.
    load_dotenv(Path.cwd() / '.env', override=False)
    parser=argparse.ArgumentParser(prog='waygraph')
    parser.add_argument('--db',default='data/relate/pilot',help='Relate directory store for graph commands')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('seed')
    source=sub.add_parser('import-docs',help='Import the published Relate documentation graph JSON')
    source.add_argument('--file',type=Path,default=Path('data/source/relate-docs-graph.json'))
    demo=sub.add_parser('demo',help='Build an isolated docs store, run the pilot, and run mutation checks')
    demo.add_argument('--db',type=Path,default=Path('data/relate/demo'))
    demo.add_argument('--output',type=Path,default=Path('experiments/results/demo'))
    demo.add_argument('--source',type=Path,default=Path('data/source/relate-docs-graph.json'))
    q=sub.add_parser('questions');q.add_argument('--limit',type=int,default=30);q.add_argument('--output',type=Path);q.add_argument('--pilot-count',type=int,default=10)
    e=sub.add_parser('pilot');e.add_argument('--limit',type=int,default=30);e.add_argument('--output',type=Path,default=Path('experiments/results'));e.add_argument('--questions-file',type=Path);e.add_argument('--split',choices=('pilot','held_out'))
    repeat=sub.add_parser('repeat-pilot',help='Run an isolated deterministic replay for each repetition')
    repeat.add_argument('--questions-file',type=Path,required=True)
    repeat.add_argument('--split',choices=('pilot','held_out'),default='pilot')
    repeat.add_argument('--repetitions',type=int,default=3)
    repeat.add_argument('--output',type=Path,default=Path('experiments/results/repeats'))
    agent=sub.add_parser('agent-eval',help='Run a tool-using agent on an isolated graph snapshot')
    agent.add_argument('--provider',choices=('gemini','anthropic','openrouter'),default='openrouter')
    agent.add_argument('--condition',choices=('cursor','native-cypher'),required=True)
    agent.add_argument('--model',default='')
    agent.add_argument('--questions-file',type=Path,required=True)
    agent.add_argument('--split',choices=('pilot','held_out'),default='pilot')
    agent.add_argument('--repetitions',type=int,default=1)
    agent.add_argument('--max-tool-calls',type=int,default=20)
    agent.add_argument('--max-tokens',type=int,default=2048)
    agent.add_argument('--source',type=Path,default=Path('data/source/relate-docs-graph.json'))
    agent.add_argument('--output',type=Path,default=Path('experiments/results/agents'))
    u=sub.add_parser('mutations',help='Run the deterministic shortcut invalidation matrix')
    u.add_argument('--output',type=Path)
    m=sub.add_parser('mutate');m.add_argument('edge_id')
    args=parser.parse_args()
    try:
        if args.command=='demo':
            if args.db.exists():
                raise ValueError(f"Demo store already exists; choose a fresh --db path: {args.db}")
            source_bytes=args.source.read_bytes()
            document=json.loads(source_bytes)
            args.output.mkdir(parents=True,exist_ok=True)
            with Graph(str(args.db)) as graph:
                imported=graph.import_source_graph(document,hashlib.sha256(source_bytes).hexdigest())
            questions_path=Path('data/questions/relate-docs-v1.jsonl')
            manifest_path=questions_path.with_suffix('.manifest.json')
            with Graph(str(args.db)) as graph:
                if questions_path.exists() and manifest_path.exists():
                    from .questions import load_question_set
                    questions=load_question_set(questions_path,expected_snapshot_id=graph.snapshot_id(),split='pilot')
                    question_result={'questions':len(questions),'source':'frozen'}
                else:
                    question_result=freeze_question_set(graph,questions_path,limit=30,pilot_count=10)
            with Graph(str(args.db)) as graph:
                pilot=run(graph,args.output,10,questions_file=questions_path,split='pilot')
            mutations=run_matrix()
            mutation_path=args.output/'mutations.json'
            mutation_path.write_text(json.dumps(mutations,indent=2)+'\n',encoding='utf-8')
            result={'import':imported,'questions':question_result,'pilot':pilot,'mutations':{**mutations,'output':str(mutation_path)}}
            print(json.dumps(result,indent=2))
            if not mutations['passed']:
                raise SystemExit(1)
            return
        if args.command=='mutations':
            result=run_matrix()
            if args.output:
                args.output.parent.mkdir(parents=True,exist_ok=True)
                args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
                result['output']=str(args.output)
            print(json.dumps(result,indent=2))
            if not result['passed']:
                raise SystemExit(1)
            return
        if args.command=='repeat-pilot':
            with Graph(args.db,read_only=True) as graph:
                result=run_repeats(graph,args.output,args.repetitions,questions_file=args.questions_file,split=args.split)
            print(json.dumps(result,indent=2))
            return
        if args.command=='agent-eval':
            result=run_agent_evaluation(source_file=args.source,question_file=args.questions_file,output=args.output,condition=args.condition,model=args.model,provider=args.provider,repetitions=args.repetitions,split=args.split,max_tool_calls=args.max_tool_calls,max_tokens=args.max_tokens)
            print(json.dumps(result,indent=2))
            return
        with Graph(args.db) as graph:
            if args.command=='seed':
                graph.seed(); result={'seeded':True}
            elif args.command=='import-docs':
                source_bytes=args.file.read_bytes()
                document=json.loads(source_bytes)
                result=graph.import_source_graph(document,hashlib.sha256(source_bytes).hexdigest())
            elif args.command=='questions':
                result=freeze_question_set(graph,args.output,limit=args.limit,pilot_count=args.pilot_count) if args.output else generate(graph,args.limit)
            elif args.command=='pilot':
                if args.split and not args.questions_file:
                    parser.error('--split requires --questions-file')
                result=run(graph,args.output,args.limit,questions_file=args.questions_file,split=args.split)
            else:
                graph.disable_edge(args.edge_id);result={'disabled_edge':args.edge_id}
        print(json.dumps(result,indent=2))
    except (ValueError,RuntimeError,Exception) as exc:
        print(f'error: {exc}',file=sys.stderr)
        raise SystemExit(1) from exc

if __name__=='__main__':
    main()
