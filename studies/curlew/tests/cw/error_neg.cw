-- A runtime error: the output so far, then the message.

main input = "before\n" ++ show (negate (minimum [-536870912, 5])) ++ "\nnever\n"
