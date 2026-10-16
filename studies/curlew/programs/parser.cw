-- input: input/parser.txt
-- Parser combinators: a parser is a function from the input to the
-- ways it can be read, a Functor and a Monad; choice, repetition, and a
-- grammar of arithmetic, evaluated line by line. Higher-order code
-- through a class: closures, partial applications and unknown calls.

data Parser a = P (String -> [(a, String)])

parse :: Parser a -> String -> [(a, String)]
parse (P p) s = p s

instance Functor Parser where
  fmap f p = P (\s -> [(f a, r) | (a, r) <- parse p s])

instance Monad Parser where
  return x = P (\s -> [(x, s)])
  p >>= f = P (\s -> concat [parse (f a) r | (a, r) <- parse p s])

infixr 2 +++

item :: Parser Char
item = P (\s -> case s of { [] -> []; (c:cs) -> [(c, cs)] })

failure :: Parser a
failure = P (\_ -> [])

(+++) :: Parser a -> Parser a -> Parser a
p +++ q = P (\s -> case parse p s of { [] -> parse q s; (r:_) -> [r] })

sat :: (Char -> Bool) -> Parser Char
sat pr = do { c <- item; if pr c then return c else failure }

char :: Char -> Parser Char
char c = sat (== c)

many, many1 :: Parser a -> Parser [a]
many p = many1 p +++ return []
many1 p = do { x <- p; xs <- many p; return (x : xs) }

space :: Parser ()
space = do { _ <- many (sat isSpace); return () }

token :: Parser a -> Parser a
token p = do { v <- p; space; return v }

symbol :: Char -> Parser Char
symbol c = token (char c)

number :: Parser Int
number = token (do { ds <- many1 (sat isDigit); return (foldl (\n d -> n * 10 + digitToInt d) 0 ds) })

expr :: Parser Int
expr = do { t <- term; rest t }
  where rest acc = (do { _ <- symbol '+'; t <- term; rest (acc + t) })
               +++ (do { _ <- symbol '-'; t <- term; rest (acc - t) })
               +++ return acc

term :: Parser Int
term = do { f <- factor; rest f }
  where rest acc = (do { _ <- symbol '*'; f <- factor; rest (acc * f) })
               +++ (do { _ <- symbol '/'; f <- factor; rest (acc `div` f) })
               +++ return acc

factor :: Parser Int
factor = number +++ (do { _ <- symbol '-'; f <- factor; return (negate f) })
                +++ (do { _ <- symbol '('; e <- expr; _ <- symbol ')'; return e })

evalLine :: String -> String
evalLine l = case parse (space >> expr) l of
  [(v, "")] -> l ++ " = " ++ show v
  [(_, rest)] -> l ++ ": unexpected " ++ show (take 10 rest)
  _ -> l ++ ": no parse"

main input = unlines (map evalLine (lines input))
