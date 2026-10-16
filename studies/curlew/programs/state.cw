-- A state monad, from scratch: label the leaves of a tree with fresh
-- numbers, then fold a list keeping a count and a sum. The monad's
-- operations go through dictionaries unless the optimiser specialises
-- them, and every bind allocates closures.

data State s a = State (s -> (a, s))

runState :: State s a -> s -> (a, s)
runState (State f) s = f s

evalState :: State s a -> s -> a
evalState m s = fst (runState m s)

instance Functor (State s) where
  fmap f m = State (\s -> case runState m s of (a, s') -> (f a, s'))

instance Monad (State s) where
  return a = State (\s -> (a, s))
  m >>= k = State (\s -> case runState m s of (a, s') -> runState (k a) s')

get :: State s s
get = State (\s -> (s, s))

put :: s -> State s ()
put s = State (\_ -> ((), s))

modify :: (s -> s) -> State s ()
modify f = State (\s -> ((), f s))

data Tree a = Leaf a | Node (Tree a) (Tree a)

build :: Int -> Int -> Tree Int
build lo hi = if lo == hi then Leaf lo
              else let m = (lo + hi) `div` 2 in Node (build lo m) (build (m + 1) hi)

fresh :: State Int Int
fresh = do
  n <- get
  put (n + 1)
  return n

label :: Tree a -> State Int (Tree (a, Int))
label (Leaf x) = do
  n <- fresh
  return (Leaf (x, n))
label (Node l r) = do
  l' <- label l
  r' <- label r
  return (Node l' r')

leaves :: Tree a -> [a]
leaves t = go t []
  where go (Leaf x) acc = x : acc
        go (Node l r) acc = go l (go r acc)

countSum :: [Int] -> State (Int, Int) ()
countSum [] = return ()
countSum (x:xs) = do
  (c, s) <- get
  put (c + 1, s + x * x)
  countSum xs

main input = unlines
  [ "labelled: " ++ show (take 8 (leaves t))
  , "labels add up to " ++ show (sum (map snd (leaves t)))
  , "count and sum of squares: " ++ show (snd (runState (countSum [1 .. 1000]) (0, 0)))
  , "fresh numbers: " ++ show (evalState (mapM (\_ -> fresh) "abcdef") 100)
  ]
  where t = evalState (label (build 1 3000)) 0
