// Command funcs reads Go files with Go's own parser and prints, tab-separated:
//
//	func  <file> <first line> <last line> <name>
//	decl  <file> <line> <last line>
//	range <file> <line> <first body line>
//
// A func line is a top-level function. Its name is the one Delve uses after
// the package path: F, T.M or (*T).M. A decl line is a statement that
// declares variables on <line> and runs on to <last line>; the variables hold
// their values only once it has run. Statements on one line are left out. A
// range line is a for-range loop that declares its key and value on <line>:
// Go copies them in at the start of each pass, so they hold no value at the
// loop's head or on its first body line.
//
//	go run funcs.go -- <file.go>...
//
// The "--" keeps go run from taking the files as more source to build.
// trace.py uses the output to show each step's whole function and to leave
// out variables not yet assigned. Run it yourself to find the names for a
// scenario's entry: go run funcs.go -- <file.go> | grep ^func
package main

import (
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
)

func main() {
	fset := token.NewFileSet()
	status := 0
	paths := os.Args[1:]
	if len(paths) > 0 && paths[0] == "--" {
		paths = paths[1:]
	}
	for _, path := range paths {
		f, err := parser.ParseFile(fset, path, nil, parser.SkipObjectResolution)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			status = 1
			continue
		}
		line := func(p token.Pos) int { return fset.Position(p).Line }
		for _, d := range f.Decls {
			if fd, ok := d.(*ast.FuncDecl); ok {
				fmt.Printf("func\t%s\t%d\t%d\t%s\n", path, line(fd.Pos()), line(fd.End()), name(fd))
			}
		}
		decl := func(from, to token.Pos) {
			if line(to) > line(from) {
				fmt.Printf("decl\t%s\t%d\t%d\n", path, line(from), line(to))
			}
		}
		ast.Inspect(f, func(n ast.Node) bool {
			switch s := n.(type) {
			case *ast.AssignStmt:
				if s.Tok == token.DEFINE {
					decl(s.Pos(), s.End())
				}
			case *ast.ValueSpec:
				decl(s.Pos(), s.End())
			case *ast.RangeStmt:
				if s.Tok == token.DEFINE && s.Key != nil {
					body := line(s.Key.Pos())
					if len(s.Body.List) > 0 {
						body = line(s.Body.List[0].Pos())
					}
					fmt.Printf("range\t%s\t%d\t%d\n", path, line(s.Key.Pos()), body)
				}
			}
			return true
		})
	}
	os.Exit(status)
}

// name gives fd's name as Delve writes it: F, T.M or (*T).M.
func name(fd *ast.FuncDecl) string {
	if fd.Recv == nil || len(fd.Recv.List) == 0 {
		return fd.Name.Name
	}
	t := fd.Recv.List[0].Type
	star := false
	if s, ok := t.(*ast.StarExpr); ok {
		star, t = true, s.X
	}
	// A generic receiver, T[K] or T[K, V], prints as T. Delve may want its
	// type parameters too; check with the dlv "funcs" command.
	switch g := t.(type) {
	case *ast.IndexExpr:
		t = g.X
	case *ast.IndexListExpr:
		t = g.X
	}
	recv := "?"
	if id, ok := t.(*ast.Ident); ok {
		recv = id.Name
	}
	if star {
		return "(*" + recv + ")." + fd.Name.Name
	}
	return recv + "." + fd.Name.Name
}
