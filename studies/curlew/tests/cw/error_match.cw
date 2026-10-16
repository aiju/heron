-- A runtime error: the output so far, then the message.

main input = "before\n" ++ show (let f (Just x) = x in f (Nothing :: Maybe Int)) ++ "\nnever\n"
