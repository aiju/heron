-- A runtime error: the output so far, then the message.

main input = "before\n" ++ show (10 `div` (length [] :: Int)) ++ "\nnever\n"
