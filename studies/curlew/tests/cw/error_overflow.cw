-- A runtime error: the output so far, then the message.

main input = "before\n" ++ show (product [1 .. 20]) ++ "\nnever\n"
