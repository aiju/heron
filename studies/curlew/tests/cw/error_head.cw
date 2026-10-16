-- A runtime error: the output so far, then the message.

main input = "before\n" ++ show (head (filter (> 3) [1, 2, 3])) ++ "\nnever\n"
