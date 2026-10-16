-- A runtime error: the output so far, then the message.

main input = "before\n" ++ show (error ("something went " ++ "wrong")) ++ "\nnever\n"
