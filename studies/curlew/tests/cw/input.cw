-- input: input/echo.txt
-- The input as a lazy string: each line of it reversed, numbered, with
-- the characters counted. Reads only as far as the output needs.

main input = unlines (zipWith number [1 ..] (lines input))
  ++ show (length input) ++ " characters, " ++ show (length (words input)) ++ " words\n"
  where number n l = show n ++ ": " ++ reverse l
