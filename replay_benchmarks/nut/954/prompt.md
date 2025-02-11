# User requirements:

1. Fix "Parser error." - The parser must succeed.
2. IMPORTANT: As you inspect the bug, YOU MUST find out exactly which AST node it failed to parse and, more IMPORTANTLY, which node it parsed PREVIOUSLY. Understanding parser problems requires understanding which production rule we are in and that requires knowing the current as well as previous tokens. Only once you fully understand the failing context, propose a fix.


## Supplementary Information
Here are all caught and uncaught errors in the recording. Maybe you can use them:
```js
[
  {
    "point": "16550446236665572707685049477103635",
    "error": `Expected number, identifier, '(', or '[', got equals
    at parseFactor (http://localhost:5173/src/parser/parseFactor.ts:23:11)
    at parseTerm (http://localhost:5173/src/parser/parseTerm.ts:4:14)
    at parseExpression (http://localhost:5173/src/parser/parseExpression.ts:4:14)
    at parseStatement (http://localhost:5173/src/parser/parseStatement.ts:44:10)
    at parseBlock (http://localhost:5173/src/parser/parseBlock.ts:31:23)
    at parseFunctionDeclaration (http://localhost:5173/src/parser/parseFunctionDeclaration.ts:50:16)
    at parseStatement (http://localhost:5173/src/parser/parseStatement.ts:29:12)
    at parseProgram (http://localhost:5173/src/parser/parseProgram.ts:22:23)
    at Parser.parse (http://localhost:5173/src/parser/parser.ts:41:19)
    at Parser.step (http://localhost:5173/src/parser/parser.ts:52:12)`
  }
]
```


Bug recording: https://app.replay.io/recording/98d54a0b-bf17-443d-b819-ff0496487a0a?point=16550446236665572707685049477103635
