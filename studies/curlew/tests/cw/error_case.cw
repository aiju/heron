-- A runtime error: the output so far, then the message.

main input = "before\n" ++ show (case [1, 2] of { [] -> 0; [x] -> x }) ++ "\nnever\n"
